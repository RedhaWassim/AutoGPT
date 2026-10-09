"""Provider registration for Eden AI — metadata and billing (auth lives in ``_auth.py``)."""

from backend.sdk import BlockCostType, ProviderBuilder

# Eden AI returns the USD ``cost`` of every Universal AI call and the expert
# model blocks report it as ``provider_cost``. Bill 150 credits per USD, the
# same 1.5x margin as the platform's other pass-through gateways. The LLM
# blocks keep their per-model costs from the LLM catalog.
edenai = (
    ProviderBuilder("edenai")
    .with_description("One API for 500+ LLMs and expert AI models")
    .with_supported_auth_types("api_key")
    .with_base_cost(150, BlockCostType.COST_USD)
    .build()
)
