import atexit
import logging
import multiprocessing
import os
import signal
import sys
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import contextmanager
from multiprocessing.pool import AsyncResult, Pool
from typing import TYPE_CHECKING, Any, Generator, Optional, TypeVar, cast

from redis.lock import Lock as RedisLock

from backend.blocks.io import AgentOutputBlock
from backend.data.model import GraphExecutionStats, NodeExecutionStats
from backend.data.notifications import (
    AgentRunData,
    LowBalanceData,
    NotificationEventDTO,
    NotificationType,
)
from backend.util.exceptions import InsufficientBalanceError

if TYPE_CHECKING:
    from backend.executor import DatabaseManager
    from backend.notifications.notifications import NotificationManager

from autogpt_libs.utils.cache import thread_cached

from backend.blocks.agent import AgentExecutorBlock
from backend.data import redis
from backend.data.block import (
    Block,
    BlockData,
    BlockInput,
    BlockSchema,
    BlockType,
    get_block,
)
from backend.data.execution import (
    ExecutionQueue,
    ExecutionStatus,
    GraphExecutionEntry,
    NodeExecutionEntry,
    NodeExecutionResult,
    merge_execution_input,
    parse_execution_output,
)
from backend.data.graph import GraphModel, Link, Node
from backend.executor.utils import (
    UsageTransactionMetadata,
    block_usage_cost,
    execution_usage_cost,
)
from backend.integrations.creds_manager import IntegrationCredentialsManager
from backend.util import json
from backend.util.decorator import error_logged, time_measured
from backend.util.file import clean_exec_files
from backend.util.logging import configure_logging
from backend.util.process import set_service_name
from backend.util.service import (
    AppService,
    close_service_client,
    expose,
    get_service_client,
)
from backend.util.settings import Settings
from backend.util.type import convert

logger = logging.getLogger(__name__)
settings = Settings()


class LogMetadata:
    def __init__(
        self,
        user_id: str,
        graph_eid: str,
        graph_id: str,
        node_eid: str,
        node_id: str,
        block_name: str,
    ):
        self.metadata = {
            "component": "ExecutionManager",
            "user_id": user_id,
            "graph_eid": graph_eid,
            "graph_id": graph_id,
            "node_eid": node_eid,
            "node_id": node_id,
            "block_name": block_name,
        }
        self.prefix = f"[ExecutionManager|uid:{user_id}|gid:{graph_id}|nid:{node_id}]|geid:{graph_eid}|nid:{node_eid}|{block_name}]"

    def info(self, msg: str, **extra):
        msg = self._wrap(msg, **extra)
        logger.info(msg, extra={"json_fields": {**self.metadata, **extra}})

    def warning(self, msg: str, **extra):
        msg = self._wrap(msg, **extra)
        logger.warning(msg, extra={"json_fields": {**self.metadata, **extra}})

    def error(self, msg: str, **extra):
        msg = self._wrap(msg, **extra)
        logger.error(msg, extra={"json_fields": {**self.metadata, **extra}})

    def debug(self, msg: str, **extra):
        msg = self._wrap(msg, **extra)
        logger.debug(msg, extra={"json_fields": {**self.metadata, **extra}})

    def exception(self, msg: str, **extra):
        msg = self._wrap(msg, **extra)
        logger.exception(msg, extra={"json_fields": {**self.metadata, **extra}})

    def _wrap(self, msg: str, **extra):
        extra_msg = str(extra or "")
        if len(extra_msg) > 1000:
            extra_msg = extra_msg[:1000] + "..."
        return f"{self.prefix} {msg} {extra_msg}"


T = TypeVar("T")
ExecutionStream = Generator[NodeExecutionEntry, None, None]


def execute_node(
    db_client: "DatabaseManager",
    creds_manager: IntegrationCredentialsManager,
    data: NodeExecutionEntry,
    execution_stats: NodeExecutionStats | None = None,
) -> ExecutionStream:
    """
    Execute a node in the graph. This will trigger a block execution on a node,
    persist the execution result, and return the subsequent node to be executed.

    Args:
        db_client: The client to send execution updates to the server.
        creds_manager: The manager to acquire and release credentials.
        data: The execution data for executing the current node.
        execution_stats: The execution statistics to be updated.

    Returns:
        The subsequent node to be enqueued, or None if there is no subsequent node.
    """
    user_id = data.user_id
    graph_exec_id = data.graph_exec_id
    graph_id = data.graph_id
    node_exec_id = data.node_exec_id
    node_id = data.node_id

    def update_execution_status(status: ExecutionStatus) -> NodeExecutionResult:
        """Sets status and fetches+broadcasts the latest state of the node execution"""
        exec_update = db_client.update_node_execution_status(node_exec_id, status)
        db_client.send_execution_update(exec_update)
        return exec_update

    node = db_client.get_node(node_id)

    node_block = node.block

    def push_output(output_name: str, output_data: Any) -> None:
        db_client.upsert_execution_output(
            node_exec_id=node_exec_id,
            output_name=output_name,
            output_data=output_data,
        )

    log_metadata = LogMetadata(
        user_id=user_id,
        graph_eid=graph_exec_id,
        graph_id=graph_id,
        node_eid=node_exec_id,
        node_id=node_id,
        block_name=node_block.name,
    )

    # Sanity check: validate the execution input.
    input_data, error = validate_exec(node, data.data, resolve_input=False)
    if input_data is None:
        log_metadata.error(f"Skip execution, input validation error: {error}")
        push_output("error", error)
        update_execution_status(ExecutionStatus.FAILED)
        return

    # Re-shape the input data for agent block.
    # AgentExecutorBlock specially separate the node input_data & its input_default.
    if isinstance(node_block, AgentExecutorBlock):
        input_data = {**node.input_default, "data": input_data}
    data.data = input_data

    # Execute the node
    input_data_str = json.dumps(input_data)
    input_size = len(input_data_str)
    log_metadata.info("Executed node with input", input=input_data_str)
    update_execution_status(ExecutionStatus.RUNNING)

    # Inject extra execution arguments for the blocks via kwargs
    extra_exec_kwargs: dict = {
        "graph_id": graph_id,
        "node_id": node_id,
        "graph_exec_id": graph_exec_id,
        "node_exec_id": node_exec_id,
        "user_id": user_id,
    }

    # Last-minute fetch credentials + acquire a system-wide read-write lock to prevent
    # changes during execution. ⚠️ This means a set of credentials can only be used by
    # one (running) block at a time; simultaneous execution of blocks using same
    # credentials is not supported.
    creds_lock = None
    input_model = cast(type[BlockSchema], node_block.input_schema)
    for field_name, input_type in input_model.get_credentials_fields().items():
        credentials_meta = input_type(**input_data[field_name])
        credentials, creds_lock = creds_manager.acquire(user_id, credentials_meta.id)
        extra_exec_kwargs[field_name] = credentials

    output_size = 0
    try:
        outputs: dict[str, Any] = {}
        for output_name, output_data in node_block.execute(
            input_data, **extra_exec_kwargs
        ):
            output_data = json.convert_pydantic_to_json(output_data)
            output_size += len(json.dumps(output_data))
            log_metadata.info("Node produced output", **{output_name: output_data})
            push_output(output_name, output_data)
            outputs[output_name] = output_data
            for execution in _enqueue_next_nodes(
                db_client=db_client,
                node=node,
                output=(output_name, output_data),
                user_id=user_id,
                graph_exec_id=graph_exec_id,
                graph_id=graph_id,
                log_metadata=log_metadata,
            ):
                yield execution

        update_execution_status(ExecutionStatus.COMPLETED)

    except Exception as e:
        error_msg = str(e)
        push_output("error", error_msg)
        update_execution_status(ExecutionStatus.FAILED)

        for execution in _enqueue_next_nodes(
            db_client=db_client,
            node=node,
            output=("error", error_msg),
            user_id=user_id,
            graph_exec_id=graph_exec_id,
            graph_id=graph_id,
            log_metadata=log_metadata,
        ):
            yield execution

        raise e
    finally:
        # Ensure credentials are released even if execution fails
        if creds_lock and creds_lock.locked():
            try:
                creds_lock.release()
            except Exception as e:
                log_metadata.error(f"Failed to release credentials lock: {e}")

        # Update execution stats
        if execution_stats is not None:
            execution_stats = execution_stats.model_copy(
                update=node_block.execution_stats.model_dump()
            )
            execution_stats.input_size = input_size
            execution_stats.output_size = output_size


def _enqueue_next_nodes(
    db_client: "DatabaseManager",
    node: Node,
    output: BlockData,
    user_id: str,
    graph_exec_id: str,
    graph_id: str,
    log_metadata: LogMetadata,
) -> list[NodeExecutionEntry]:
    def add_enqueued_execution(
        node_exec_id: str, node_id: str, block_id: str, data: BlockInput
    ) -> NodeExecutionEntry:
        exec_update = db_client.update_node_execution_status(
            node_exec_id, ExecutionStatus.QUEUED, data
        )
        db_client.send_execution_update(exec_update)
        return NodeExecutionEntry(
            user_id=user_id,
            graph_exec_id=graph_exec_id,
            graph_id=graph_id,
            node_exec_id=node_exec_id,
            node_id=node_id,
            block_id=block_id,
            data=data,
        )

    def register_next_executions(node_link: Link) -> list[NodeExecutionEntry]:
        enqueued_executions = []
        next_output_name = node_link.source_name
        next_input_name = node_link.sink_name
        next_node_id = node_link.sink_id

        next_data = parse_execution_output(output, next_output_name)
        if next_data is None:
            return enqueued_executions

        next_node = db_client.get_node(next_node_id)

        # Multiple node can register the same next node, we need this to be atomic
        # To avoid same execution to be enqueued multiple times,
        # Or the same input to be consumed multiple times.
        with synchronized(f"upsert_input-{next_node_id}-{graph_exec_id}"):
            # Add output data to the earliest incomplete execution, or create a new one.
            next_node_exec_id, next_node_input = db_client.upsert_execution_input(
                node_id=next_node_id,
                graph_exec_id=graph_exec_id,
                input_name=next_input_name,
                input_data=next_data,
            )

            # Complete missing static input pins data using the last execution input.
            static_link_names = {
                link.sink_name
                for link in next_node.input_links
                if link.is_static and link.sink_name not in next_node_input
            }
            if static_link_names and (
                latest_execution := db_client.get_latest_node_execution(
                    next_node_id, graph_exec_id
                )
            ):
                for name in static_link_names:
                    next_node_input[name] = latest_execution.input_data.get(name)

            # Validate the input data for the next node.
            next_node_input, validation_msg = validate_exec(next_node, next_node_input)
            suffix = f"{next_output_name}>{next_input_name}~{next_node_exec_id}:{validation_msg}"

            # Incomplete input data, skip queueing the execution.
            if not next_node_input:
                log_metadata.warning(f"Skipped queueing {suffix}")
                return enqueued_executions

            # Input is complete, enqueue the execution.
            log_metadata.info(f"Enqueued {suffix}")
            enqueued_executions.append(
                add_enqueued_execution(
                    node_exec_id=next_node_exec_id,
                    node_id=next_node_id,
                    block_id=next_node.block_id,
                    data=next_node_input,
                )
            )

            # Next execution stops here if the link is not static.
            if not node_link.is_static:
                return enqueued_executions

            # If link is static, there could be some incomplete executions waiting for it.
            # Load and complete the input missing input data, and try to re-enqueue them.
            for iexec in db_client.get_incomplete_node_executions(
                next_node_id, graph_exec_id
            ):
                idata = iexec.input_data
                ineid = iexec.node_exec_id

                static_link_names = {
                    link.sink_name
                    for link in next_node.input_links
                    if link.is_static and link.sink_name not in idata
                }
                for input_name in static_link_names:
                    idata[input_name] = next_node_input[input_name]

                idata, msg = validate_exec(next_node, idata)
                suffix = f"{next_output_name}>{next_input_name}~{ineid}:{msg}"
                if not idata:
                    log_metadata.info(f"Enqueueing static-link skipped: {suffix}")
                    continue
                log_metadata.info(f"Enqueueing static-link execution {suffix}")
                enqueued_executions.append(
                    add_enqueued_execution(
                        node_exec_id=iexec.node_exec_id,
                        node_id=next_node_id,
                        block_id=next_node.block_id,
                        data=idata,
                    )
                )
            return enqueued_executions

    return [
        execution
        for link in node.output_links
        for execution in register_next_executions(link)
    ]


def validate_exec(
    node: Node,
    data: BlockInput,
    resolve_input: bool = True,
) -> tuple[BlockInput | None, str]:
    """
    Validate the input data for a node execution.

    Args:
        node: The node to execute.
        data: The input data for the node execution.
        resolve_input: Whether to resolve dynamic pins into dict/list/object.

    Returns:
        A tuple of the validated data and the block name.
        If the data is invalid, the first element will be None, and the second element
        will be an error message.
        If the data is valid, the first element will be the resolved input data, and
        the second element will be the block name.
    """
    node_block: Block | None = get_block(node.block_id)
    if not node_block:
        return None, f"Block for {node.block_id} not found."
    schema = node_block.input_schema

    # Convert non-matching data types to the expected input schema.
    for name, data_type in schema.__annotations__.items():
        if (value := data.get(name)) and (type(value) is not data_type):
            data[name] = convert(value, data_type)

    # Input data (without default values) should contain all required fields.
    error_prefix = f"Input data missing or mismatch for `{node_block.name}`:"
    if missing_links := schema.get_missing_links(data, node.input_links):
        return None, f"{error_prefix} unpopulated links {missing_links}"

    # Merge input data with default values and resolve dynamic dict/list/object pins.
    input_default = schema.get_input_defaults(node.input_default)
    data = {**input_default, **data}
    if resolve_input:
        data = merge_execution_input(data)

    # Input data post-merge should contain all required fields from the schema.
    if missing_input := schema.get_missing_input(data):
        return None, f"{error_prefix} missing input {missing_input}"

    # Last validation: Validate the input values against the schema.
    if error := schema.get_mismatch_error(data):
        error_message = f"{error_prefix} {error}"
        logger.error(error_message)
        return None, error_message

    return data, node_block.name


class Executor:
    """
    This class contains event handlers for the process pool executor events.

    The main events are:
        on_node_executor_start: Initialize the process that executes the node.
        on_node_execution: Execution logic for a node.

        on_graph_executor_start: Initialize the process that executes the graph.
        on_graph_execution: Execution logic for a graph.

    The execution flow:
        1. Graph execution request is added to the queue.
        2. Graph executor loop picks the request from the queue.
        3. Graph executor loop submits the graph execution request to the executor pool.
      [on_graph_execution]
        4. Graph executor initialize the node execution queue.
        5. Graph executor adds the starting nodes to the node execution queue.
        6. Graph executor waits for all nodes to be executed.
      [on_node_execution]
        7. Node executor picks the node execution request from the queue.
        8. Node executor executes the node.
        9. Node executor enqueues the next executed nodes to the node execution queue.
    """

    @classmethod
    def on_node_executor_start(cls):
        configure_logging()
        set_service_name("NodeExecutor")
        redis.connect()
        cls.pid = os.getpid()
        cls.db_client = get_db_client()
        cls.creds_manager = IntegrationCredentialsManager()

        # Set up shutdown handlers
        cls.shutdown_lock = threading.Lock()
        atexit.register(cls.on_node_executor_stop)  # handle regular shutdown
        signal.signal(  # handle termination
            signal.SIGTERM, lambda _, __: cls.on_node_executor_sigterm()
        )

    @classmethod
    def on_node_executor_stop(cls):
        if not cls.shutdown_lock.acquire(blocking=False):
            return  # already shutting down

        logger.info(f"[on_node_executor_stop {cls.pid}] ⏳ Releasing locks...")
        cls.creds_manager.release_all_locks()
        logger.info(f"[on_node_executor_stop {cls.pid}] ⏳ Disconnecting Redis...")
        redis.disconnect()
        logger.info(f"[on_node_executor_stop {cls.pid}] ⏳ Disconnecting DB manager...")
        close_service_client(cls.db_client)
        logger.info(f"[on_node_executor_stop {cls.pid}] ✅ Finished cleanup")

    @classmethod
    def on_node_executor_sigterm(cls):
        llprint(f"[on_node_executor_sigterm {cls.pid}] ⚠️ SIGTERM received")
        if not cls.shutdown_lock.acquire(blocking=False):
            return  # already shutting down

        llprint(f"[on_node_executor_stop {cls.pid}] ⏳ Releasing locks...")
        cls.creds_manager.release_all_locks()
        llprint(f"[on_node_executor_stop {cls.pid}] ⏳ Disconnecting Redis...")
        redis.disconnect()
        llprint(f"[on_node_executor_stop {cls.pid}] ✅ Finished cleanup")
        sys.exit(0)

    @classmethod
    @error_logged
    def on_node_execution(
        cls,
        q: ExecutionQueue[NodeExecutionEntry],
        node_exec: NodeExecutionEntry,
    ) -> NodeExecutionStats:
        log_metadata = LogMetadata(
            user_id=node_exec.user_id,
            graph_eid=node_exec.graph_exec_id,
            graph_id=node_exec.graph_id,
            node_eid=node_exec.node_exec_id,
            node_id=node_exec.node_id,
            block_name="-",
        )

        execution_stats = NodeExecutionStats()
        timing_info, _ = cls._on_node_execution(
            q, node_exec, log_metadata, execution_stats
        )
        execution_stats.walltime = timing_info.wall_time
        execution_stats.cputime = timing_info.cpu_time

        if isinstance(execution_stats.error, Exception):
            execution_stats.error = str(execution_stats.error)
        cls.db_client.update_node_execution_stats(
            node_exec.node_exec_id, execution_stats
        )
        return execution_stats

    @classmethod
    @time_measured
    def _on_node_execution(
        cls,
        q: ExecutionQueue[NodeExecutionEntry],
        node_exec: NodeExecutionEntry,
        log_metadata: LogMetadata,
        stats: NodeExecutionStats | None = None,
    ):
        try:
            log_metadata.info(f"Start node execution {node_exec.node_exec_id}")
            for execution in execute_node(
                db_client=cls.db_client,
                creds_manager=cls.creds_manager,
                data=node_exec,
                execution_stats=stats,
            ):
                q.add(execution)
            log_metadata.info(f"Finished node execution {node_exec.node_exec_id}")
        except Exception as e:
            # Avoid user error being marked as an actual error.
            if isinstance(e, ValueError):
                log_metadata.info(
                    f"Failed node execution {node_exec.node_exec_id}: {e}"
                )
            else:
                log_metadata.exception(
                    f"Failed node execution {node_exec.node_exec_id}: {e}"
                )

            if stats is not None:
                stats.error = e

    @classmethod
    def on_graph_executor_start(cls):
        configure_logging()
        set_service_name("GraphExecutor")

        cls.db_client = get_db_client()
        cls.pool_size = settings.config.num_node_workers
        cls.pid = os.getpid()
        cls.notification_service = get_notification_service()
        cls._init_node_executor_pool()
        logger.info(
            f"Graph executor {cls.pid} started with {cls.pool_size} node workers"
        )

        # Set up shutdown handler
        atexit.register(cls.on_graph_executor_stop)

    @classmethod
    def on_graph_executor_stop(cls):
        prefix = f"[on_graph_executor_stop {cls.pid}]"
        logger.info(f"{prefix} ⏳ Terminating node executor pool...")
        cls.executor.terminate()
        logger.info(f"{prefix} ⏳ Disconnecting DB manager...")
        close_service_client(cls.db_client)
        logger.info(f"{prefix} ✅ Finished cleanup")

    @classmethod
    def _init_node_executor_pool(cls):
        cls.executor = Pool(
            processes=cls.pool_size,
            initializer=cls.on_node_executor_start,
        )

    @classmethod
    @error_logged
    def on_graph_execution(
        cls, graph_exec: GraphExecutionEntry, cancel: threading.Event
    ):
        log_metadata = LogMetadata(
            user_id=graph_exec.user_id,
            graph_eid=graph_exec.graph_exec_id,
            graph_id=graph_exec.graph_id,
            node_id="*",
            node_eid="*",
            block_name="-",
        )
        exec_meta = cls.db_client.update_graph_execution_start_time(
            graph_exec.graph_exec_id
        )
        cls.db_client.send_execution_update(exec_meta)
        timing_info, (exec_stats, status, error) = cls._on_graph_execution(
            graph_exec, cancel, log_metadata
        )
        exec_stats.walltime = timing_info.wall_time
        exec_stats.cputime = timing_info.cpu_time
        exec_stats.error = str(error)

        if graph_exec_result := cls.db_client.update_graph_execution_stats(
            graph_exec_id=graph_exec.graph_exec_id,
            status=status,
            stats=exec_stats,
        ):
            cls.db_client.send_execution_update(graph_exec_result)

        cls._handle_agent_run_notif(graph_exec, exec_stats)

    @classmethod
    def _charge_usage(
        cls,
        node_exec: NodeExecutionEntry,
        execution_count: int,
        execution_stats: GraphExecutionStats,
    ) -> int:
        block = get_block(node_exec.block_id)
        if not block:
            logger.error(f"Block {node_exec.block_id} not found.")
            return execution_count

        cost, matching_filter = block_usage_cost(block=block, input_data=node_exec.data)
        if cost > 0:
            cls.db_client.spend_credits(
                user_id=node_exec.user_id,
                cost=cost,
                metadata=UsageTransactionMetadata(
                    graph_exec_id=node_exec.graph_exec_id,
                    graph_id=node_exec.graph_id,
                    node_exec_id=node_exec.node_exec_id,
                    node_id=node_exec.node_id,
                    block_id=node_exec.block_id,
                    block=block.name,
                    input=matching_filter,
                ),
            )
            execution_stats.cost += cost

        cost, execution_count = execution_usage_cost(execution_count)
        if cost > 0:
            cls.db_client.spend_credits(
                user_id=node_exec.user_id,
                cost=cost,
                metadata=UsageTransactionMetadata(
                    graph_exec_id=node_exec.graph_exec_id,
                    graph_id=node_exec.graph_id,
                    input={
                        "execution_count": execution_count,
                        "charge": "Execution Cost",
                    },
                ),
            )
            execution_stats.cost += cost

        return execution_count

    @classmethod
    @time_measured
    def _on_graph_execution(
        cls,
        graph_exec: GraphExecutionEntry,
        cancel: threading.Event,
        log_metadata: LogMetadata,
    ) -> tuple[GraphExecutionStats, ExecutionStatus, Exception | None]:
        """
        Returns:
            dict: The execution statistics of the graph execution.
            ExecutionStatus: The final status of the graph execution.
            Exception | None: The error that occurred during the execution, if any.
        """
        log_metadata.info(f"Start graph execution {graph_exec.graph_exec_id}")
        execution_stats = GraphExecutionStats()
        execution_status = ExecutionStatus.RUNNING
        error = None
        finished = False

        def cancel_handler():
            nonlocal execution_status

            while not cancel.is_set():
                cancel.wait(1)
            if finished:
                return
            execution_status = ExecutionStatus.TERMINATED
            cls.executor.terminate()
            log_metadata.info(f"Terminated graph execution {graph_exec.graph_exec_id}")
            cls._init_node_executor_pool()

        cancel_thread = threading.Thread(target=cancel_handler)
        cancel_thread.start()

        try:
            queue = ExecutionQueue[NodeExecutionEntry]()
            for node_exec in graph_exec.start_node_execs:
                queue.add(node_exec)

            exec_cost_counter = 0
            running_executions: dict[str, AsyncResult] = {}

            def make_exec_callback(exec_data: NodeExecutionEntry):
                def callback(result: object):
                    running_executions.pop(exec_data.node_id)

                    if not isinstance(result, NodeExecutionStats):
                        return

                    nonlocal execution_stats
                    execution_stats.node_count += 1
                    execution_stats.nodes_cputime += result.cputime
                    execution_stats.nodes_walltime += result.walltime
                    if (err := result.error) and isinstance(err, Exception):
                        execution_stats.node_error_count += 1

                    if _graph_exec := cls.db_client.update_graph_execution_stats(
                        graph_exec_id=exec_data.graph_exec_id,
                        status=execution_status,
                        stats=execution_stats,
                    ):
                        cls.db_client.send_execution_update(_graph_exec)
                    else:
                        logger.error(
                            "Callback for "
                            f"finished node execution #{exec_data.node_exec_id} "
                            "could not update execution stats "
                            f"for graph execution #{exec_data.graph_exec_id}; "
                            f"triggered while graph exec status = {execution_status}"
                        )

                return callback

            while not queue.empty():
                if cancel.is_set():
                    execution_status = ExecutionStatus.TERMINATED
                    return execution_stats, execution_status, error

                exec_data = queue.get()

                # Avoid parallel execution of the same node.
                execution = running_executions.get(exec_data.node_id)
                if execution and not execution.ready():
                    # TODO (performance improvement):
                    #   Wait for the completion of the same node execution is blocking.
                    #   To improve this we need a separate queue for each node.
                    #   Re-enqueueing the data back to the queue will disrupt the order.
                    execution.wait()

                log_metadata.debug(
                    f"Dispatching node execution {exec_data.node_exec_id} "
                    f"for node {exec_data.node_id}",
                )

                try:
                    exec_cost_counter = cls._charge_usage(
                        node_exec=exec_data,
                        execution_count=exec_cost_counter + 1,
                        execution_stats=execution_stats,
                    )
                except InsufficientBalanceError as error:
                    node_exec_id = exec_data.node_exec_id
                    cls.db_client.upsert_execution_output(
                        node_exec_id=node_exec_id,
                        output_name="error",
                        output_data=str(error),
                    )

                    execution_status = ExecutionStatus.FAILED
                    exec_update = cls.db_client.update_node_execution_status(
                        node_exec_id, execution_status
                    )
                    cls.db_client.send_execution_update(exec_update)

                    cls._handle_low_balance_notif(
                        graph_exec.user_id,
                        graph_exec.graph_id,
                        execution_stats,
                        error,
                    )
                    raise

                running_executions[exec_data.node_id] = cls.executor.apply_async(
                    cls.on_node_execution,
                    (queue, exec_data),
                    callback=make_exec_callback(exec_data),
                )

                # Avoid terminating graph execution when some nodes are still running.
                while queue.empty() and running_executions:
                    log_metadata.debug(
                        f"Queue empty; running nodes: {list(running_executions.keys())}"
                    )
                    for node_id, execution in list(running_executions.items()):
                        if cancel.is_set():
                            execution_status = ExecutionStatus.TERMINATED
                            return execution_stats, execution_status, error

                        if not queue.empty():
                            break  # yield to parent loop to execute new queue items

                        log_metadata.debug(f"Waiting on execution of node {node_id}")
                        execution.wait(3)

            log_metadata.info(f"Finished graph execution {graph_exec.graph_exec_id}")

        except Exception as e:
            error = e
        finally:
            if error:
                log_metadata.error(
                    f"Failed graph execution {graph_exec.graph_exec_id}: {error}"
                )
                execution_status = ExecutionStatus.FAILED
            else:
                execution_status = ExecutionStatus.COMPLETED

            if not cancel.is_set():
                finished = True
                cancel.set()
            cancel_thread.join()
            clean_exec_files(graph_exec.graph_exec_id)

            return execution_stats, execution_status, error

    @classmethod
    def _handle_agent_run_notif(
        cls,
        graph_exec: GraphExecutionEntry,
        exec_stats: GraphExecutionStats,
    ):
        metadata = cls.db_client.get_graph_metadata(
            graph_exec.graph_id, graph_exec.graph_version
        )
        outputs = cls.db_client.get_node_execution_results(
            graph_exec.graph_exec_id,
            block_ids=[AgentOutputBlock().id],
        )

        named_outputs = [
            {
                key: value[0] if key == "name" else value
                for key, value in output.output_data.items()
            }
            for output in outputs
        ]

        event = NotificationEventDTO(
            user_id=graph_exec.user_id,
            type=NotificationType.AGENT_RUN,
            data=AgentRunData(
                outputs=named_outputs,
                agent_name=metadata.name if metadata else "Unknown Agent",
                credits_used=exec_stats.cost,
                execution_time=exec_stats.walltime,
                graph_id=graph_exec.graph_id,
                node_count=exec_stats.node_count,
            ).model_dump(),
        )

        cls.notification_service.queue_notification(event)

    @classmethod
    def _handle_low_balance_notif(
        cls,
        user_id: str,
        graph_id: str,
        exec_stats: GraphExecutionStats,
        e: InsufficientBalanceError,
    ):
        shortfall = e.balance - e.amount
        metadata = cls.db_client.get_graph_metadata(graph_id)
        base_url = (
            settings.config.frontend_base_url or settings.config.platform_base_url
        )
        cls.notification_service.queue_notification(
            NotificationEventDTO(
                user_id=user_id,
                type=NotificationType.LOW_BALANCE,
                data=LowBalanceData(
                    current_balance=exec_stats.cost,
                    billing_page_link=f"{base_url}/profile/credits",
                    shortfall=shortfall,
                    agent_name=metadata.name if metadata else "Unknown Agent",
                ).model_dump(),
            )
        )


class ExecutionManager(AppService):
    def __init__(self):
        super().__init__()
        self.pool_size = settings.config.num_graph_workers
        self.queue = ExecutionQueue[GraphExecutionEntry]()
        self.active_graph_runs: dict[str, tuple[Future, threading.Event]] = {}

    @classmethod
    def get_port(cls) -> int:
        return settings.config.execution_manager_port

    def run_service(self):
        from backend.integrations.credentials_store import IntegrationCredentialsStore

        self.credentials_store = IntegrationCredentialsStore()

        logger.info(f"[{self.service_name}] ⏳ Spawn max-{self.pool_size} workers...")
        self.executor = ProcessPoolExecutor(
            max_workers=self.pool_size,
            initializer=Executor.on_graph_executor_start,
        )

        logger.info(f"[{self.service_name}] ⏳ Connecting to Redis...")
        redis.connect()

        sync_manager = multiprocessing.Manager()
        while True:
            graph_exec_data = self.queue.get()
            graph_exec_id = graph_exec_data.graph_exec_id
            logger.debug(
                f"[ExecutionManager] Dispatching graph execution {graph_exec_id}"
            )
            cancel_event = sync_manager.Event()
            future = self.executor.submit(
                Executor.on_graph_execution, graph_exec_data, cancel_event
            )
            self.active_graph_runs[graph_exec_id] = (future, cancel_event)
            future.add_done_callback(
                lambda _: self.active_graph_runs.pop(graph_exec_id, None)
            )

    def cleanup(self):
        super().cleanup()

        logger.info(f"[{self.service_name}] ⏳ Shutting down graph executor pool...")
        self.executor.shutdown(cancel_futures=True)

        logger.info(f"[{self.service_name}] ⏳ Disconnecting Redis...")
        redis.disconnect()

    @property
    def db_client(self) -> "DatabaseManager":
        return get_db_client()

    @expose
    def add_execution(
        self,
        graph_id: str,
        data: BlockInput,
        user_id: str,
        graph_version: Optional[int] = None,
        preset_id: str | None = None,
    ) -> GraphExecutionEntry:
        graph: GraphModel | None = self.db_client.get_graph(
            graph_id=graph_id, user_id=user_id, version=graph_version
        )
        if not graph:
            raise ValueError(f"Graph #{graph_id} not found.")

        graph.validate_graph(for_run=True)
        self._validate_node_input_credentials(graph, user_id)

        nodes_input = []
        for node in graph.starting_nodes:
            input_data = {}
            block = node.block

            # Note block should never be executed.
            if block.block_type == BlockType.NOTE:
                continue

            # Extract request input data, and assign it to the input pin.
            if block.block_type == BlockType.INPUT:
                input_name = node.input_default.get("name")
                if input_name and input_name in data:
                    input_data = {"value": data[input_name]}

            # Extract webhook payload, and assign it to the input pin
            webhook_payload_key = f"webhook_{node.webhook_id}_payload"
            if (
                block.block_type in (BlockType.WEBHOOK, BlockType.WEBHOOK_MANUAL)
                and node.webhook_id
            ):
                if webhook_payload_key not in data:
                    raise ValueError(
                        f"Node {block.name} #{node.id} webhook payload is missing"
                    )
                input_data = {"payload": data[webhook_payload_key]}

            input_data, error = validate_exec(node, input_data)
            if input_data is None:
                raise ValueError(error)
            else:
                nodes_input.append((node.id, input_data))

        if not nodes_input:
            raise ValueError(
                "No starting nodes found for the graph, make sure an AgentInput or blocks with no inbound links are present as starting nodes."
            )

        graph_exec = self.db_client.create_graph_execution(
            graph_id=graph_id,
            graph_version=graph.version,
            nodes_input=nodes_input,
            user_id=user_id,
            preset_id=preset_id,
        )
        self.db_client.send_execution_update(graph_exec)

        graph_exec_entry = GraphExecutionEntry(
            user_id=user_id,
            graph_id=graph_id,
            graph_version=graph_version or 0,
            graph_exec_id=graph_exec.id,
            start_node_execs=[
                NodeExecutionEntry(
                    user_id=user_id,
                    graph_exec_id=node_exec.graph_exec_id,
                    graph_id=node_exec.graph_id,
                    node_exec_id=node_exec.node_exec_id,
                    node_id=node_exec.node_id,
                    block_id=node_exec.block_id,
                    data=node_exec.input_data,
                )
                for node_exec in graph_exec.node_executions
            ],
        )
        self.queue.add(graph_exec_entry)

        return graph_exec_entry

    @expose
    def cancel_execution(self, graph_exec_id: str) -> None:
        """
        Mechanism:
        1. Set the cancel event
        2. Graph executor's cancel handler thread detects the event, terminates workers,
           reinitializes worker pool, and returns.
        3. Update execution statuses in DB and set `error` outputs to `"TERMINATED"`.
        """
        if graph_exec_id not in self.active_graph_runs:
            logger.warning(
                f"Graph execution #{graph_exec_id} not active/running: "
                "possibly already completed/cancelled."
            )
        else:
            future, cancel_event = self.active_graph_runs[graph_exec_id]
            if not cancel_event.is_set():
                cancel_event.set()
                future.result()

        # Update the status of the graph & node executions
        self.db_client.update_graph_execution_stats(
            graph_exec_id,
            ExecutionStatus.TERMINATED,
        )
        node_execs = self.db_client.get_node_execution_results(
            graph_exec_id=graph_exec_id,
            statuses=[
                ExecutionStatus.QUEUED,
                ExecutionStatus.RUNNING,
                ExecutionStatus.INCOMPLETE,
            ],
        )
        self.db_client.update_node_execution_status_batch(
            [node_exec.node_exec_id for node_exec in node_execs],
            ExecutionStatus.TERMINATED,
        )
        for node_exec in node_execs:
            node_exec.status = ExecutionStatus.TERMINATED
            self.db_client.send_execution_update(node_exec)

    def _validate_node_input_credentials(self, graph: GraphModel, user_id: str):
        """Checks all credentials for all nodes of the graph"""

        for node in graph.nodes:
            block = node.block

            # Find any fields of type CredentialsMetaInput
            credentials_fields = cast(
                type[BlockSchema], block.input_schema
            ).get_credentials_fields()
            if not credentials_fields:
                continue

            for field_name, credentials_meta_type in credentials_fields.items():
                credentials_meta = credentials_meta_type.model_validate(
                    node.input_default[field_name]
                )
                # Fetch the corresponding Credentials and perform sanity checks
                credentials = self.credentials_store.get_creds_by_id(
                    user_id, credentials_meta.id
                )
                if not credentials:
                    raise ValueError(
                        f"Unknown credentials #{credentials_meta.id} "
                        f"for node #{node.id} input '{field_name}'"
                    )
                if (
                    credentials.provider != credentials_meta.provider
                    or credentials.type != credentials_meta.type
                ):
                    logger.warning(
                        f"Invalid credentials #{credentials.id} for node #{node.id}: "
                        "type/provider mismatch: "
                        f"{credentials_meta.type}<>{credentials.type};"
                        f"{credentials_meta.provider}<>{credentials.provider}"
                    )
                    raise ValueError(
                        f"Invalid credentials #{credentials.id} for node #{node.id}: "
                        "type/provider mismatch"
                    )


# ------- UTILITIES ------- #


@thread_cached
def get_db_client() -> "DatabaseManager":
    from backend.executor import DatabaseManager

    return get_service_client(DatabaseManager)


@thread_cached
def get_notification_service() -> "NotificationManager":
    from backend.notifications import NotificationManager

    return get_service_client(NotificationManager)


@contextmanager
def synchronized(key: str, timeout: int = 60):
    lock: RedisLock = redis.get_redis().lock(f"lock:{key}", timeout=timeout)
    try:
        lock.acquire()
        yield
    finally:
        if lock.locked():
            lock.release()


def llprint(message: str):
    """
    Low-level print/log helper function for use in signal handlers.
    Regular log/print statements are not allowed in signal handlers.
    """
    if logger.getEffectiveLevel() == logging.DEBUG:
        os.write(sys.stdout.fileno(), (message + "\n").encode())
