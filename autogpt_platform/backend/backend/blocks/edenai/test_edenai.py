"""Unit tests for the Eden AI expert model blocks.

Complements the ``test_mock`` harness in each block (exercised by
``test_available_blocks``) with direct coverage of the Universal AI client:
request bodies, async job polling, failed results, file uploads and cost
reporting.
"""

from typing import cast
from unittest import mock

import pytest

from backend.blocks.edenai._api import (
    EDENAI_API_URL,
    EdenAIClient,
    EdenAIError,
    EdenAIResult,
    is_async_model,
    resolve_file_input,
)
from backend.blocks.edenai._auth import TEST_CREDENTIALS, TEST_CREDENTIALS_INPUT
from backend.blocks.edenai.expert_model import EdenAIExpertModelBlock
from backend.blocks.edenai.text import EdenAIExtractTextBlock
from backend.data.execution import ExecutionContext
from backend.util.exceptions import BlockExecutionError
from backend.util.file import MediaFileType


def _response(data: dict) -> mock.Mock:
    response = mock.Mock()
    response.json.return_value = data
    return response


def _requests(post=None, get=None) -> mock.Mock:
    requests = mock.Mock()
    requests.post = mock.AsyncMock(side_effect=post)
    requests.get = mock.AsyncMock(side_effect=get)
    return requests


def test_is_async_model():
    assert is_async_model("audio/speech_to_text_async/deepgram")
    assert is_async_model("ocr/ocr_async/amazon")
    assert not is_async_model("ocr/ocr/mistral")
    assert not is_async_model("ocr")


@pytest.mark.asyncio
async def test_run_sync_model_sends_compact_request():
    success = {
        "status": "success",
        "cost": "0.0015",
        "provider": "mistral",
        "feature": "ocr",
        "subfeature": "ocr",
        "output": {"text": "Invoice #42"},
    }
    requests = _requests(post=[_response(success)])
    with mock.patch("backend.blocks.edenai._api.Requests", return_value=requests):
        result = await EdenAIClient("key").run(
            "ocr/ocr/mistral",
            {"file": "https://example.com/a.png", "language": None},
            fallbacks=["google"],
        )

    assert result == EdenAIResult(
        output={"text": "Invoice #42"}, cost=0.0015, provider="mistral"
    )
    args, kwargs = requests.post.call_args
    assert args[0] == f"{EDENAI_API_URL}/universal-ai"
    assert kwargs["headers"] == {"Authorization": "Bearer key"}
    assert kwargs["json"] == {
        "model": "ocr/ocr/mistral",
        "input": {"file": "https://example.com/a.png"},
        "output_format": "compact",
        "fallbacks": ["google"],
    }


@pytest.mark.asyncio
async def test_run_async_model_polls_until_done():
    job = {"status": "processing", "public_id": "job-1", "cost": "0"}
    done = {
        "status": "success",
        "public_id": "job-1",
        "cost": "0.0052",
        "provider": "deepgram",
        "output": {"text": "Hello world"},
    }
    requests = _requests(post=[_response(job)], get=[_response(job), _response(done)])
    with (
        mock.patch("backend.blocks.edenai._api.Requests", return_value=requests),
        mock.patch("backend.blocks.edenai._api.asyncio.sleep", mock.AsyncMock()),
    ):
        result = await EdenAIClient("key").run(
            "audio/speech_to_text_async/deepgram", {"file": "https://e.com/a.mp3"}
        )

    assert result.output == {"text": "Hello world"}
    assert result.cost == 0.0052
    assert requests.post.call_args.args[0] == f"{EDENAI_API_URL}/universal-ai/async"
    assert requests.get.call_count == 2
    assert (
        requests.get.call_args.args[0] == f"{EDENAI_API_URL}/universal-ai/async/job-1"
    )


@pytest.mark.asyncio
async def test_run_raises_on_failed_status():
    failed = {
        "status": "fail",
        "cost": "0",
        "provider": "mistral",
        "output": None,
        "error": {"message": "Unsupported file type"},
    }
    requests = _requests(post=[_response(failed)])
    with mock.patch("backend.blocks.edenai._api.Requests", return_value=requests):
        with pytest.raises(EdenAIError, match="Unsupported file type"):
            await EdenAIClient("key").run("ocr/ocr/mistral", {"file": "x"})


@pytest.mark.asyncio
async def test_resolve_file_input_passes_urls_through():
    client = mock.Mock(spec=EdenAIClient)
    file = await resolve_file_input(
        client,
        MediaFileType("https://example.com/a.pdf"),
        cast(ExecutionContext, mock.Mock()),
    )
    assert file == "https://example.com/a.pdf"
    client.upload.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_file_input_uploads_workspace_files():
    client = mock.Mock(spec=EdenAIClient)
    client.upload = mock.AsyncMock(return_value="file-123")
    with mock.patch(
        "backend.blocks.edenai._api.store_media_file",
        mock.AsyncMock(return_value="data:application/pdf;base64,JVBERi0="),
    ):
        file = await resolve_file_input(
            client,
            MediaFileType("workspace://abc"),
            cast(ExecutionContext, mock.Mock()),
        )

    assert file == "file-123"
    content, filename, mime_type = client.upload.call_args.args
    assert content == b"%PDF-"
    assert filename == "upload.pdf"
    assert mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_block_reports_provider_cost():
    block = EdenAIExpertModelBlock()
    result = EdenAIResult(output={"items": []}, cost=0.0005, provider="amazon")
    with (
        mock.patch.object(block, "_run_model", mock.AsyncMock(return_value=result)),
        mock.patch.object(block, "merge_stats") as merge_stats,
    ):
        outputs = [
            o
            async for o in block.run(
                EdenAIExpertModelBlock.Input.model_validate(
                    {
                        "credentials": TEST_CREDENTIALS_INPUT,
                        "model": "text/named_entity_recognition/amazon",
                        "input": {"text": "hi"},
                    }
                ),
                credentials=TEST_CREDENTIALS,
            )
        ]

    assert outputs == [
        ("output", {"items": []}),
        ("provider", "amazon"),
        ("cost", 0.0005),
    ]
    stats = merge_stats.call_args.args[0]
    assert stats.provider_cost == 0.0005
    assert stats.provider_cost_type == "cost_usd"


@pytest.mark.asyncio
async def test_block_wraps_errors():
    block = EdenAIExtractTextBlock()
    with mock.patch.object(
        block, "_run_model", mock.AsyncMock(side_effect=EdenAIError("boom"))
    ):
        with pytest.raises(BlockExecutionError, match="boom"):
            await block._call(TEST_CREDENTIALS, "ocr/ocr/mistral", {"file": "x"})
