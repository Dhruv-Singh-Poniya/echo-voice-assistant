"""Selects and caches the active LLM provider based on config."""
from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import AssistantTurn, LLMProvider, ToolCall


@lru_cache(maxsize=None)
def get_provider() -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if settings.llm_provider == "gateway":
        from .gateway_provider import GatewayProvider

        return GatewayProvider()
    # default: local, free, no key
    from .ollama_provider import OllamaProvider

    return OllamaProvider()


__all__ = ["get_provider", "LLMProvider", "AssistantTurn", "ToolCall"]
