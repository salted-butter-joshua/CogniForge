"""LLM factory — Anthropic / OpenRouter / LiteLLM / MiniMax routing."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from src.config import get_settings
from src.models.router import configure_provider_env, resolve_role_model

logger = logging.getLogger(__name__)


def _ensure_env() -> None:
    # Re-push provider keys/base URLs into os.environ on every build so that
    # changes to settings (e.g. a different key for a new run) take effect
    # without restarting the process. It only writes env vars, so it's cheap.
    configure_provider_env()


def _minimax_extra_body() -> dict[str, Any]:
    """Reduce MiniMax thinking-only replies; prefer answer in main content."""
    return {
        "reasoning_split": True,
    }


def _build_litellm(model: str, temperature: float) -> BaseChatModel:
    from langchain_litellm import ChatLiteLLM

    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "timeout": settings.single_llm_timeout,
        "max_retries": 2,
    }
    if "minimax" in model.lower():
        kwargs["model_kwargs"] = {"extra_body": _minimax_extra_body()}
    return ChatLiteLLM(**kwargs)


def _build_openrouter(model: str, temperature: float) -> BaseChatModel:
    """OpenRouter via OpenAI-compatible client."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    # strip openrouter/ prefix for OpenAI client — base_url handles routing
    bare = model.removeprefix("openrouter/")
    return ChatOpenAI(
        model=bare,
        temperature=temperature,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.single_llm_timeout,
        max_retries=2,
        default_headers={
            "HTTP-Referer": "https://github.com/loop-engineering/cogniforge",
            "X-Title": "CogniForge",
        },
    )


def _build_anthropic(model: str, temperature: float) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    settings = get_settings()
    return ChatAnthropic(
        model=model,
        temperature=temperature,
        api_key=settings.anthropic_api_key,
        timeout=settings.single_llm_timeout,
        max_retries=2,
    )


def _build_openai(model: str, temperature: float) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.single_llm_timeout,
        max_retries=2,
    )


def _build_minimax(model: str, temperature: float) -> BaseChatModel:
    """MiniMax direct via OpenAI-compatible endpoint."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.minimax_api_key,
        base_url=settings.minimax_base_url,
        timeout=settings.single_llm_timeout,
        max_retries=2,
        model_kwargs={"extra_body": _minimax_extra_body()},
    )


def _base_llm(role: str, temperature: float) -> BaseChatModel:
    _ensure_env()
    settings = get_settings()
    model = resolve_role_model(role, settings)
    router = settings.llm_router

    logger.debug("LLM role=%s router=%s model=%s", role, router, model)

    if router == "litellm":
        return _build_litellm(model, temperature)
    if router == "openrouter":
        return _build_openrouter(model, temperature)
    if router == "anthropic":
        return _build_anthropic(model, temperature)
    if router == "minimax":
        return _build_minimax(model, temperature)
    return _build_openai(model, temperature)


def student_llm() -> BaseChatModel:
    return _base_llm("student", temperature=0.35)


def persona_llm() -> BaseChatModel:
    return _base_llm("persona", temperature=0.7)


def judge_llm() -> BaseChatModel:
    return _base_llm("judge", temperature=0.0)


def observer_llm() -> BaseChatModel:
    return _base_llm("observer", temperature=0.3)


def material_llm() -> BaseChatModel:
    return _base_llm("material", temperature=0.2)
