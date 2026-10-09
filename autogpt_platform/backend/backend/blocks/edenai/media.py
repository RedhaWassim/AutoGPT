from typing import Any

from backend.blocks._base import (
    BlockCategory,
    BlockEffect,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.data.execution import ExecutionContext
from backend.data.model import SchemaField
from backend.util.file import MediaFileType, store_media_file

from ._api import EdenAIClient, EdenAIResult, resolve_file_input
from ._auth import (
    TEST_CREDENTIALS,
    TEST_CREDENTIALS_INPUT,
    EdenAICredentials,
    EdenAICredentialsField,
    EdenAICredentialsInput,
)
from ._base import EdenAIBlockBase
from ._models import AudioOutput, ImageOutput, TranscriptionOutput

# 1x1 transparent PNG and a few MP3 header bytes, so block tests never hit the network.
_TEST_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
_TEST_AUDIO = "data:audio/mpeg;base64,SUQzBAAAAAAAAA=="


class EdenAITextToSpeechBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        text: str = SchemaField(description="Text to convert to speech")
        model: str = SchemaField(
            description="Eden AI text-to-speech model, `audio/tts/<provider>[/<model>]` "
            "(amazon, deepgram, elevenlabs, google, microsoft, openai, ...).",
            default="audio/tts/openai/gpt-4o-mini-tts",
        )
        voice: str = SchemaField(
            description="Provider voice name or ID. The provider default is used when empty.",
            default="",
        )
        audio_format: str = SchemaField(
            description="Audio format, e.g. 'mp3' or 'wav'. The provider default is used when empty.",
            default="",
            advanced=True,
        )

    class Output(BlockSchemaOutput):
        audio: MediaFileType = SchemaField(description="The generated speech")

    def __init__(self):
        super().__init__(
            id="c62b6db4-8007-4017-a95e-843986fe64d3",
            description="Converts text to speech with an Eden AI expert model.",
            categories={BlockCategory.AI, BlockCategory.MULTIMEDIA},
            effect=BlockEffect.WORKSPACE,
            input_schema=EdenAITextToSpeechBlock.Input,
            output_schema=EdenAITextToSpeechBlock.Output,
            test_input={"credentials": TEST_CREDENTIALS_INPUT, "text": "Hello"},
            test_credentials=TEST_CREDENTIALS,
            test_output=[
                ("audio", lambda x: x.startswith(("workspace://", "data:"))),
            ],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={"audio_resource_url": _TEST_AUDIO},
                    cost=0.0002,
                    provider="openai",
                )
            },
        )

    async def run(
        self,
        input_data: Input,
        *,
        credentials: EdenAICredentials,
        execution_context: ExecutionContext,
        **kwargs,
    ) -> BlockOutput:
        result = await self._call(
            credentials,
            input_data.model,
            {
                "text": input_data.text,
                "voice": input_data.voice or None,
                "audio_format": input_data.audio_format or None,
            },
        )
        # Eden AI resource URLs expire; keep a copy in the user's workspace.
        yield "audio", await store_media_file(
            file=MediaFileType(
                AudioOutput.model_validate(result.output).audio_resource_url
            ),
            execution_context=execution_context,
            return_format="for_block_output",
        )


class EdenAIGenerateImageBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        prompt: str = SchemaField(
            description="Text description of the image to generate"
        )
        model: str = SchemaField(
            description="Eden AI image generation model, `image/generation/<provider>[/<model>]` "
            "(bytedance, google, leonardo, minimax, openai, stabilityai, ...).",
            default="image/generation/openai/gpt-image-1-mini",
        )
        resolution: str = SchemaField(
            description="Image size such as '1024x1024'. The provider default is used when empty.",
            default="",
        )
        fallbacks: list[str] = SchemaField(
            description="Up to 3 fallback providers tried in order if the primary one fails.",
            default_factory=list,
            advanced=True,
        )

    class Output(BlockSchemaOutput):
        image: MediaFileType = SchemaField(description="The generated image")

    def __init__(self):
        super().__init__(
            id="774d1c27-53ad-4c62-851b-971495717a4a",
            description="Generates an image from a text prompt with an Eden AI expert model.",
            categories={BlockCategory.AI, BlockCategory.MULTIMEDIA},
            effect=BlockEffect.WORKSPACE,
            input_schema=EdenAIGenerateImageBlock.Input,
            output_schema=EdenAIGenerateImageBlock.Output,
            test_input={
                "credentials": TEST_CREDENTIALS_INPUT,
                "prompt": "A lighthouse at dusk",
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[
                ("image", lambda x: x.startswith(("workspace://", "data:"))),
            ],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={"image_resource_url": _TEST_IMAGE},
                    cost=0.011,
                    provider="openai",
                )
            },
        )

    async def run(
        self,
        input_data: Input,
        *,
        credentials: EdenAICredentials,
        execution_context: ExecutionContext,
        **kwargs,
    ) -> BlockOutput:
        result = await self._call(
            credentials,
            input_data.model,
            {"text": input_data.prompt, "resolution": input_data.resolution or None},
            input_data.fallbacks,
        )
        # Eden AI resource URLs expire; keep a copy in the user's workspace.
        yield "image", await store_media_file(
            file=MediaFileType(ImageOutput.model_validate(result.output).url()),
            execution_context=execution_context,
            return_format="for_block_output",
        )


class EdenAISpeechToTextBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        audio: MediaFileType = SchemaField(
            description="Audio or video file to transcribe: a URL, a workspace file or a data URI.",
        )
        model: str = SchemaField(
            description="Eden AI speech-to-text model, "
            "`audio/speech_to_text_async/<provider>[/<model>]` "
            "(amazon, assembly, deepgram, gladia, google, ...).",
            default="audio/speech_to_text_async/deepgram/nova-3",
        )
        language: str = SchemaField(
            description="Language code of the speech, e.g. 'en'. Detected by most providers when empty.",
            default="",
        )
        fallbacks: list[str] = SchemaField(
            description="Up to 3 fallback providers tried in order if the primary one fails.",
            default_factory=list,
            advanced=True,
        )

    class Output(BlockSchemaOutput):
        text: str = SchemaField(description="The transcription")
        speakers: list[dict[str, Any]] = SchemaField(
            description="Speaker segments, when the provider returns diarization"
        )

    def __init__(self):
        super().__init__(
            id="c3da3755-2c32-4515-98f8-109d50ebd891",
            description="Transcribes speech from an audio or video file with an Eden AI expert model.",
            categories={BlockCategory.AI, BlockCategory.MULTIMEDIA},
            effect=BlockEffect.READ,
            input_schema=EdenAISpeechToTextBlock.Input,
            output_schema=EdenAISpeechToTextBlock.Output,
            test_input={
                "credentials": TEST_CREDENTIALS_INPUT,
                "audio": "https://example.com/meeting.mp3",
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("text", "Hello world"), ("speakers", [])],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={
                        "text": "Hello world",
                        "diarization": {"total_speakers": 1, "entries": []},
                    },
                    cost=0.0052,
                    provider="deepgram",
                )
            },
        )

    async def run(
        self,
        input_data: Input,
        *,
        credentials: EdenAICredentials,
        execution_context: ExecutionContext,
        **kwargs,
    ) -> BlockOutput:
        file = await resolve_file_input(
            EdenAIClient(credentials.api_key.get_secret_value()),
            input_data.audio,
            execution_context,
        )
        result = await self._call(
            credentials,
            input_data.model,
            {"file": file, "language": input_data.language or None},
            input_data.fallbacks,
        )
        output = TranscriptionOutput.model_validate(result.output)
        yield "text", output.text
        yield "speakers", output.diarization.entries
