from typing import Any

from backend.blocks._base import (
    BlockCategory,
    BlockEffect,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.data.model import SchemaField

from ._api import EdenAIResult
from ._auth import (
    TEST_CREDENTIALS,
    TEST_CREDENTIALS_INPUT,
    EdenAICredentials,
    EdenAICredentialsField,
    EdenAICredentialsInput,
)
from ._base import EdenAIBlockBase


class EdenAIExpertModelBlock(EdenAIBlockBase):
    class Input(BlockSchemaInput):
        credentials: EdenAICredentialsInput = EdenAICredentialsField()
        model: str = SchemaField(
            description="Eden AI expert model, `feature/subfeature/provider[/model]`, e.g. "
            "'text/named_entity_recognition/amazon', 'ocr/financial_parser/google' or "
            "'image/object_detection/amazon'. Async models (subfeature ending in "
            "'_async') are polled until done. The catalog is at https://api.edenai.run/v3/info.",
            placeholder="text/named_entity_recognition/amazon",
        )
        input: dict[str, Any] = SchemaField(
            description="Feature specific input, e.g. {'text': '...', 'language': 'en'} "
            "or {'file': '<URL or Eden AI file ID>'}. Some providers require a language code.",
        )
        provider_params: dict[str, Any] = SchemaField(
            description="Provider-specific parameters forwarded as-is.",
            default_factory=dict,
            advanced=True,
        )
        fallbacks: list[str] = SchemaField(
            description="Up to 3 fallback providers tried in order if the primary one fails.",
            default_factory=list,
            advanced=True,
        )

    class Output(BlockSchemaOutput):
        output: Any = SchemaField(description="Normalized output of the expert model")
        provider: str = SchemaField(description="Provider that served the request")
        cost: float = SchemaField(description="Cost of the request in USD")

    def __init__(self):
        super().__init__(
            id="e0156aef-203d-4a54-8c1a-6fcd50b4c8a7",
            description="Calls any Eden AI expert model (OCR, document parsing, image "
            "analysis, text analysis, web, audio, ...) through the Universal AI endpoint.",
            categories={BlockCategory.AI},
            effect=BlockEffect.READ,
            input_schema=EdenAIExpertModelBlock.Input,
            output_schema=EdenAIExpertModelBlock.Output,
            test_input={
                "credentials": TEST_CREDENTIALS_INPUT,
                "model": "text/named_entity_recognition/amazon",
                "input": {"text": "Eden AI is based in Montpellier.", "language": "en"},
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[
                ("output", {"items": [{"entity": "Montpellier", "category": "LOC"}]}),
                ("provider", "amazon"),
                ("cost", 0.0005),
            ],
            test_mock={
                "_run_model": lambda *args, **kwargs: EdenAIResult(
                    output={"items": [{"entity": "Montpellier", "category": "LOC"}]},
                    cost=0.0005,
                    provider="amazon",
                )
            },
        )

    async def run(
        self, input_data: Input, *, credentials: EdenAICredentials, **kwargs
    ) -> BlockOutput:
        result = await self._call(
            credentials,
            input_data.model,
            input_data.input,
            input_data.fallbacks,
            input_data.provider_params or None,
        )
        yield "output", result.output
        yield "provider", result.provider or ""
        yield "cost", result.cost or 0.0
