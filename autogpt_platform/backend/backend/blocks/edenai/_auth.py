"""Eden AI credentials, shared by the expert model blocks and the LLM blocks."""

from typing import Literal

from pydantic import SecretStr

from backend.data.model import APIKeyCredentials, CredentialsField, CredentialsMetaInput
from backend.integrations.providers import ProviderName

EdenAICredentials = APIKeyCredentials
EdenAICredentialsInput = CredentialsMetaInput[
    Literal[ProviderName.EDENAI],
    Literal["api_key"],
]


def EdenAICredentialsField() -> EdenAICredentialsInput:
    return CredentialsField(
        description="The Eden AI integration requires an API key.",
    )


TEST_CREDENTIALS = APIKeyCredentials(
    id="5d3f7c1e-8a2b-4c6d-9e0f-1a2b3c4d5e6f",
    provider="edenai",
    api_key=SecretStr("mock-edenai-api-key"),
    title="Mock Eden AI API key",
    expires_at=None,
)

TEST_CREDENTIALS_INPUT = {
    "provider": TEST_CREDENTIALS.provider,
    "id": TEST_CREDENTIALS.id,
    "type": TEST_CREDENTIALS.type,
    "title": TEST_CREDENTIALS.title,
}
