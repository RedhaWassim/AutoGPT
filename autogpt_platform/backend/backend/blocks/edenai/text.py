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
from backend.util.file import MediaFileType

from ._api import EdenAIClient, EdenAIResult, resolve_file_input
from ._auth import (
    TEST_CREDENTIALS,
    TEST_CREDENTIALS_INPUT,
    EdenAICredentials,
    EdenAICredentialsField,
    EdenAICredentialsInput,
)
from ._base import EdenAIBlockBase
from ._models import ModerationOutput, TextOutput

FALLBACKS_DESCRIPTION = (
    "Up to 3 fallback providers tried in order if the primary one fails, "
    "e.g. ['google'] or ['ocr/ocr/google']."
)


class EdenAIExtractTextBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        file: MediaFileType = SchemaField(
            description="Image or PDF to read: a URL, a workspace file or a data URI.",
        )
        model: str = SchemaField(
            description="Eden AI OCR model, `ocr/ocr/<provider>[/<model>]` "
            "(amazon, google, microsoft, mistral, ...).",
            default="ocr/ocr/mistral",
        )
        language: str = SchemaField(
            description="Language code of the document, e.g. 'en'. Most providers detect it.",
            default="",
            advanced=True,
        )
        fallbacks: list[str] = SchemaField(
            description=FALLBACKS_DESCRIPTION, default_factory=list, advanced=True
        )

    class Output(BlockSchemaOutput):
        text: str = SchemaField(description="Text extracted from the document")

    def __init__(self):
        super().__init__(
            id="9cb7d717-54ec-4208-a6ce-91f6c00b5525",
            description="Extracts the text of an image or PDF (OCR) with an Eden AI expert model.",
            categories={BlockCategory.AI, BlockCategory.TEXT},
            effect=BlockEffect.READ,
            input_schema=EdenAIExtractTextBlock.Input,
            output_schema=EdenAIExtractTextBlock.Output,
            test_input={
                "credentials": TEST_CREDENTIALS_INPUT,
                "file": "https://example.com/invoice.png",
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("text", "Invoice #42")],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={"text": "Invoice #42"}, cost=0.0015, provider="mistral"
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
            input_data.file,
            execution_context,
        )
        result = await self._call(
            credentials,
            input_data.model,
            {"file": file, "language": input_data.language or None},
            input_data.fallbacks,
        )
        yield "text", TextOutput.model_validate(result.output).text


class EdenAITranslateTextBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        text: str = SchemaField(description="Text to translate")
        target_language: str = SchemaField(
            description="Target language code, e.g. 'fr'", placeholder="fr"
        )
        source_language: str = SchemaField(
            description="Source language code, e.g. 'en'. Detected when empty.",
            default="",
        )
        model: str = SchemaField(
            description="Eden AI translation model, "
            "`translation/automatic_translation/<provider>[/<model>]` "
            "(amazon, deepl, google, microsoft, modernmt, openai, ...).",
            default="translation/automatic_translation/google",
        )
        fallbacks: list[str] = SchemaField(
            description=FALLBACKS_DESCRIPTION, default_factory=list, advanced=True
        )

    class Output(BlockSchemaOutput):
        translated_text: str = SchemaField(description="The translated text")

    def __init__(self):
        super().__init__(
            id="ecba717d-69e8-46a2-9147-38d3b9ef4e36",
            description="Translates text into another language with an Eden AI expert model.",
            categories={BlockCategory.AI, BlockCategory.TEXT},
            effect=BlockEffect.READ,
            input_schema=EdenAITranslateTextBlock.Input,
            output_schema=EdenAITranslateTextBlock.Output,
            test_input={
                "credentials": TEST_CREDENTIALS_INPUT,
                "text": "Hello",
                "target_language": "fr",
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("translated_text", "Bonjour")],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={"text": "Bonjour"}, cost=0.0001, provider="google"
                )
            },
        )

    async def run(
        self, input_data: Input, *, credentials: EdenAICredentials, **kwargs
    ) -> BlockOutput:
        result = await self._call(
            credentials,
            input_data.model,
            {
                "text": input_data.text,
                "target_language": input_data.target_language,
                "source_language": input_data.source_language or None,
            },
            input_data.fallbacks,
        )
        yield "translated_text", TextOutput.model_validate(result.output).text


class EdenAIModerateTextBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        text: str = SchemaField(description="Text to moderate")
        model: str = SchemaField(
            description="Eden AI moderation model, `text/moderation/<provider>[/<model>]` "
            "(google, microsoft, openai, ...).",
            default="text/moderation/openai",
        )
        fallbacks: list[str] = SchemaField(
            description=FALLBACKS_DESCRIPTION, default_factory=list, advanced=True
        )

    class Output(BlockSchemaOutput):
        nsfw_likelihood: int = SchemaField(
            description="Overall likelihood the text is harmful, from 1 (unlikely) to 5 (very likely)"
        )
        categories: list[dict[str, Any]] = SchemaField(
            description="Detected categories with their likelihood"
        )

    def __init__(self):
        super().__init__(
            id="7c3b4958-6543-4acd-87a1-c04d10fbff0e",
            description="Checks text for offensive, sexual, violent, hateful or self-harm "
            "content with an Eden AI expert model.",
            categories={BlockCategory.AI, BlockCategory.SAFETY},
            effect=BlockEffect.READ,
            input_schema=EdenAIModerateTextBlock.Input,
            output_schema=EdenAIModerateTextBlock.Output,
            test_input={"credentials": TEST_CREDENTIALS_INPUT, "text": "Hello there"},
            test_credentials=TEST_CREDENTIALS,
            test_output=[
                ("nsfw_likelihood", 1),
                ("categories", [{"label": "Toxic", "likelihood": 1}]),
            ],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={
                        "nsfw_likelihood": 1,
                        "items": [{"label": "Toxic", "likelihood": 1}],
                    },
                    cost=0.0,
                    provider="openai",
                )
            },
        )

    async def run(
        self, input_data: Input, *, credentials: EdenAICredentials, **kwargs
    ) -> BlockOutput:
        result = await self._call(
            credentials,
            input_data.model,
            {"text": input_data.text},
            input_data.fallbacks,
        )
        output = ModerationOutput.model_validate(result.output)
        yield "nsfw_likelihood", output.nsfw_likelihood
        yield "categories", output.items
