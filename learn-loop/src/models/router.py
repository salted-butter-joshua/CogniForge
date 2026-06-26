"""Model routing — Anthropic / OpenRouter / LiteLLM / MiniMax."""

from __future__ import annotations

import logging
import os
from typing import Any

from src.config import Settings, get_settings, load_models_config

logger = logging.getLogger(__name__)

ROLE_ENV_MAP = {
    "student": "student_model",
    "persona": "persona_model",
    "judge": "judge_model",
    "observer": "observer_model",
    "material": "material_model",
}

PLACEHOLDER_KEYS = {"", "sk-your-key", "not-set", "your-key-here"}


def _is_set(value: str | None) -> bool:
    return bool(value and value.strip() not in PLACEHOLDER_KEYS)


def configure_provider_env(settings: Settings | None = None) -> None:
    """Push API keys / base URLs into os.environ for LiteLLM & LangChain."""
    s = settings or get_settings()
    mapping = {
        "ANTHROPIC_API_KEY": s.anthropic_api_key,
        "OPENROUTER_API_KEY": s.openrouter_api_key,
        "MINIMAX_API_KEY": s.minimax_api_key,
        "OPENAI_API_KEY": s.openai_api_key,
        "MINIMAX_API_BASE": s.minimax_base_url,
        "OPENROUTER_API_BASE": s.openrouter_base_url,
        "OPENAI_API_BASE": s.openai_base_url,
    }
    for key, val in mapping.items():
        if _is_set(val):
            os.environ[key] = val.strip()


def _resolve_alias(alias: str, router: str) -> str:
    cfg = load_models_config()
    aliases = cfg.get("aliases", {})
    entry = aliases.get(alias, {})
    if isinstance(entry, dict) and router in entry:
        return entry[router]
    if isinstance(entry, dict) and "litellm" in entry:
        return entry["litellm"]
    return alias


def _preset_role_model(preset: str, role: str, settings: Settings) -> str:
    cfg = load_models_config()
    presets = cfg.get("presets", {})
    preset_cfg = presets.get(preset, {})
    alias = preset_cfg.get(role)
    if alias:
        return _resolve_alias(alias, settings.llm_router)
    env_field = ROLE_ENV_MAP[role]
    return getattr(settings, env_field)


def resolve_role_model(role: str, settings: Settings | None = None) -> str:
    """Return fully-qualified model id for a role."""
    s = settings or get_settings()
    if s.model_preset and s.model_preset != "custom":
        raw = _preset_role_model(s.model_preset, role, s)
    else:
        raw = getattr(s, ROLE_ENV_MAP[role])
    return resolve_model_id(raw, s)


def resolve_model_id(model: str, settings: Settings | None = None) -> str:
    """Normalize model string for the active router."""
    s = settings or get_settings()
    router = s.llm_router
    model = model.strip()

    # Already fully qualified
    if model.startswith(("openrouter/", "anthropic/", "minimax/", "openai/")):
        if router == "openrouter" and not model.startswith("openrouter/"):
            return f"openrouter/{model}"
        return model

    # Short alias like minimax-m2.7
    cfg = load_models_config()
    if model in cfg.get("aliases", {}):
        return _resolve_alias(model, router)

    if router == "litellm":
        if model.startswith("claude"):
            return f"anthropic/{model}"
        if "/" not in model and model.lower().startswith("minimax"):
            return f"minimax/{model}"
        return model

    if router == "openrouter":
        if model.startswith("minimax/"):
            return f"openrouter/{model}"
        if model.startswith("MiniMax-"):
            slug = model.replace("MiniMax-", "minimax-m").lower()
            return f"openrouter/minimax/{slug}"
        return f"openrouter/{model}"

    if router == "minimax":
        if model.startswith("MiniMax-"):
            return model
        if model.startswith("minimax/"):
            return model.split("/", 1)[1]
        return model

    if router == "anthropic":
        return model.removeprefix("anthropic/")

    # openai-compatible direct
    return model


def validate_api_keys(settings: Settings | None = None) -> tuple[bool, str]:
    """Validate that required API key exists for the active router."""
    s = settings or get_settings()
    router = s.llm_router

    if router == "anthropic":
        if not _is_set(s.anthropic_api_key):
            return False, "ANTHROPIC_API_KEY is required when LLM_ROUTER=anthropic"
        return True, ""

    if router == "openrouter":
        if not _is_set(s.openrouter_api_key):
            return False, "OPENROUTER_API_KEY is required when LLM_ROUTER=openrouter"
        return True, ""

    if router == "minimax":
        if not _is_set(s.minimax_api_key):
            return False, "MINIMAX_API_KEY is required when LLM_ROUTER=minimax"
        return True, ""

    if router == "openai":
        if not _is_set(s.openai_api_key):
            return False, "OPENAI_API_KEY is required when LLM_ROUTER=openai"
        return True, ""

    # litellm — at least one provider key
    if any(
        _is_set(k)
        for k in (
            s.anthropic_api_key,
            s.openrouter_api_key,
            s.minimax_api_key,
            s.openai_api_key,
        )
    ):
        return True, ""

    return (
        False,
        "Set at least one API key (MINIMAX_API_KEY, OPENROUTER_API_KEY, "
        "ANTHROPIC_API_KEY, or OPENAI_API_KEY) when LLM_ROUTER=litellm",
    )


def llm_runtime_info(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    return {
        "router": s.llm_router,
        "preset": s.model_preset,
        "models": {role: resolve_role_model(role, s) for role in ROLE_ENV_MAP},
    }
