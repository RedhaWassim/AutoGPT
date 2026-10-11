"""Shared plumbing for the Eden AI expert model blocks."""

from typing import Any

from backend.blocks._base import Block
from backend.data.model import APIKeyCredentials, NodeExecutionStats
from backend.util.exceptions import BlockExecutionError

from ._api import EdenAIClient, EdenAIResult


class EdenAIBlockBase(Block):
    """Runs an Eden AI expert model and records its USD cost for billing."""

    async def _run_model(
        self,
        credentials: APIKeyCredentials,
        model: str,
        input: dict[str, Any],
        fallbacks: list[str] | None = None,
        provider_params: dict[str, Any] | None = None,
    ) -> EdenAIResult:
        """Call the Universal AI endpoint (mocked in block tests)."""
        client = EdenAIClient(credentials.api_key.get_secret_value())
        return await client.run(model, input, fallbacks, provider_params)

    async def _call(
        self,
        credentials: APIKeyCredentials,
        model: str,
        input: dict[str, Any],
        fallbacks: list[str] | None = None,
        provider_params: dict[str, Any] | None = None,
    ) -> EdenAIResult:
        try:
            result = await self._run_model(
                credentials, model, input, fallbacks, provider_params
            )
        except Exception as e:
            raise BlockExecutionError(
                message=f"Eden AI {model} failed: {e}",
                block_name=self.name,
                block_id=self.id,
            ) from e
        if result.cost is not None:
            self.merge_stats(
                NodeExecutionStats(
                    provider_cost=result.cost, provider_cost_type="cost_usd"
                )
            )
        return result
