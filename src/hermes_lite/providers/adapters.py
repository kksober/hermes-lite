"""Provider adapter layer — config and agent creation for OpenAI-compatible APIs.

Supports OpenAI, Anthropic, DeepSeek, OpenRouter, and any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider.

    Attributes:
        provider: Backend identifier — 'openai', 'anthropic', 'deepseek', or 'openrouter'.
        model: Model name string (e.g. 'gpt-4o', 'claude-sonnet-4-20250514').
        api_key: API key. If empty, falls back to the provider's default env var.
        base_url: Custom endpoint URL for OpenAI-compatible proxies.
        context_window: Maximum context tokens (for compression hints).
    """

    provider: Literal["openai", "anthropic", "deepseek", "openrouter"] = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    context_window: int = 128_000

    def _effective_api_key(self) -> str | None:
        """Resolve the API key: explicit value → env var → None."""
        if self.api_key:
            return self.api_key
        env_map: dict[str, str] = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        return os.getenv(env_map.get(self.provider, ""))

    def _model_string(self) -> str:
        """Build the pydantic-ai model identifier string.

        For 'openai' we return just the model name since the default provider is OpenAI.
        For all others we prepend `<provider>:` so pydantic-ai can resolve the adapter.
        """
        if self.provider == "openai":
            return self.model
        # Map to pydantic-ai known provider names
        provider_map: dict[str, str] = {
            "anthropic": "anthropic",
            "deepseek": "deepseek",
            "openrouter": "openrouter",
        }
        prefix = provider_map.get(self.provider, self.provider)
        return f"{prefix}:{self.model}"


def create_agent(
    config: ProviderConfig,
    *,
    system_prompt: str = "",
    tools: list | None = None,
    defer_model_check: bool = False,
) -> Agent[None, str]:
    """Create a configured pydantic-ai Agent from a ProviderConfig.

    Args:
        config: Provider configuration.
        system_prompt: Static system prompt string.
        tools: Optional list of pydantic-ai Tool objects.
        defer_model_check: If True, don't validate the model until first run.

    Returns:
        A pydantic_ai.Agent instance ready for `.run()`.
    """
    model_str = config._model_string()
    api_key = config._effective_api_key()

    # Set API key in environment if provided and not already set
    if api_key:
        env_map: dict[str, str] = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        key_name = env_map.get(config.provider, "")
        if key_name and not os.getenv(key_name):
            os.environ[key_name] = api_key

    # Configure base URL via env if provided (for proxies and non-OpenAI providers)
    base_url_map: dict[str, str] = {
        "openai": "OPENAI_BASE_URL",
        "deepseek": "DEEPSEEK_BASE_URL",
        "openrouter": "OPENROUTER_BASE_URL",
    }
    if config.base_url:
        env_var = base_url_map.get(config.provider)
        if env_var and not os.getenv(env_var):
            os.environ[env_var] = config.base_url
    # Default DeepSeek base URL if none set
    elif config.provider == "deepseek" and not os.getenv("DEEPSEEK_BASE_URL"):
        os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"

    agent_kwargs: dict = {
        "model": model_str,
        "system_prompt": system_prompt,
        "defer_model_check": defer_model_check,
    }
    if tools:
        agent_kwargs["tools"] = tools

    return Agent[None, str](**agent_kwargs)
