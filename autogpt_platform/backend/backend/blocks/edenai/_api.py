"""Client for the Eden AI V3 Universal AI (expert models) endpoint.

https://www.edenai.co/docs/v3/expert-models — models are addressed as
``feature/subfeature/provider[/model]`` (e.g. ``ocr/ocr/mistral``). Sync
features answer on ``POST /v3/universal-ai``; features whose subfeature ends
in ``_async`` create a job on ``POST /v3/universal-ai/async`` that is polled
until it leaves the ``processing`` state.
"""

import asyncio
import base64
import time
from io import BytesIO
from typing import Any

from pydantic import BaseModel

from backend.data.execution import ExecutionContext
from backend.util.file import MediaFileType, parse_data_uri, store_media_file
from backend.util.request import Requests

EDENAI_API_URL = "https://api.edenai.run/v3"

ASYNC_POLL_INTERVAL_SECONDS = 3.0
ASYNC_MAX_WAIT_SECONDS = 900.0


class EdenAIError(Exception):
    """Eden AI reported a failed expert model call."""


class EdenAIResult(BaseModel):
    output: Any = None
    cost: float | None = None
    provider: str | None = None


class _UniversalAIResponse(BaseModel):
    status: str
    cost: float | None = None
    provider: str | None = None
    output: Any = None
    error: dict[str, Any] | None = None
    public_id: str | None = None

    def to_result(self) -> EdenAIResult:
        if self.status == "fail":
            message = (self.error or {}).get("message")
            raise EdenAIError(message or "Eden AI request failed")
        return EdenAIResult(output=self.output, cost=self.cost, provider=self.provider)


class _UploadResponse(BaseModel):
    file_id: str


def is_async_model(model: str) -> bool:
    parts = model.split("/")
    return len(parts) > 1 and parts[1].endswith("_async")


class EdenAIClient:
    def __init__(self, api_key: str, base_url: str = EDENAI_API_URL):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def run(
        self,
        model: str,
        input: dict[str, Any],
        fallbacks: list[str] | None = None,
        provider_params: dict[str, Any] | None = None,
    ) -> EdenAIResult:
        """Call an expert model and return its normalized output and USD cost."""
        body: dict[str, Any] = {
            "model": model,
            "input": {k: v for k, v in input.items() if v is not None},
            # Drops base64 media and dense position data, keeping the
            # *_resource_url download links next to them.
            "output_format": "compact",
        }
        if fallbacks:
            body["fallbacks"] = fallbacks
        if provider_params:
            body["provider_params"] = provider_params

        if is_async_model(model):
            return await self._run_job(body)
        response = await Requests().post(
            f"{self.base_url}/universal-ai", headers=self.headers, json=body
        )
        return _UniversalAIResponse.model_validate(response.json()).to_result()

    async def upload(self, content: bytes, filename: str, mime_type: str) -> str:
        """Upload a file to Eden AI storage and return its file ID."""
        response = await Requests().post(
            f"{self.base_url}/upload",
            headers=self.headers,
            files=[("file", (filename, BytesIO(content), mime_type))],
            data={},
        )
        return _UploadResponse.model_validate(response.json()).file_id

    async def _run_job(self, body: dict[str, Any]) -> EdenAIResult:
        response = await Requests().post(
            f"{self.base_url}/universal-ai/async", headers=self.headers, json=body
        )
        job = _UniversalAIResponse.model_validate(response.json())
        if not job.public_id:
            raise EdenAIError("Eden AI did not return a job ID")

        deadline = time.monotonic() + ASYNC_MAX_WAIT_SECONDS
        while job.status == "processing":
            if time.monotonic() >= deadline:
                raise EdenAIError(
                    f"Eden AI job {job.public_id} did not finish within "
                    f"{int(ASYNC_MAX_WAIT_SECONDS)} seconds"
                )
            await asyncio.sleep(ASYNC_POLL_INTERVAL_SECONDS)
            response = await Requests().get(
                f"{self.base_url}/universal-ai/async/{job.public_id}",
                headers=self.headers,
                params={"output_format": "compact"},
            )
            job = _UniversalAIResponse.model_validate(response.json())
        return job.to_result()


async def resolve_file_input(
    client: EdenAIClient,
    file: MediaFileType,
    execution_context: ExecutionContext,
) -> str:
    """Turn a block file input into something Eden AI accepts: a URL or a file ID.

    Public URLs are passed through for Eden AI to fetch. Workspace files and
    data URIs are uploaded to Eden AI's file storage first.
    """
    if file.startswith(("http://", "https://")):
        return file
    data_uri = await store_media_file(
        file=file,
        execution_context=execution_context,
        return_format="for_external_api",
    )
    parsed = parse_data_uri(data_uri)
    if parsed is None:
        raise EdenAIError("Unsupported file input")
    mime_type, payload = parsed
    extension = mime_type.split("/")[-1].split("+")[0] or "bin"
    return await client.upload(
        base64.b64decode(payload), f"upload.{extension}", mime_type
    )
