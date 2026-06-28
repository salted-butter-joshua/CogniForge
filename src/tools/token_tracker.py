"""Track LLM token usage per graph step and in total for one run.

A single LangChain callback (``token_callback``) is attached to every model in
the factory. ``logged_node`` sets the current step name before each node runs,
so usage is attributed to the right pipeline step. ``run_service`` resets the
tracker at the start of a run and reads ``snapshot()`` to surface counts.
"""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

_lock = threading.Lock()
_current_step = "other"


def set_current_step(step: str) -> None:
    global _current_step
    _current_step = step or "other"


class _Tracker:
    def __init__(self) -> None:
        self.by_step: dict[str, dict[str, int]] = {}
        self.input = 0
        self.output = 0
        self.calls = 0

    def reset(self) -> None:
        with _lock:
            self.by_step = {}
            self.input = 0
            self.output = 0
            self.calls = 0

    def add(self, step: str, inp: int, out: int) -> None:
        with _lock:
            s = self.by_step.setdefault(
                step, {"input": 0, "output": 0, "total": 0, "calls": 0}
            )
            s["input"] += inp
            s["output"] += out
            s["total"] += inp + out
            s["calls"] += 1
            self.input += inp
            self.output += out
            self.calls += 1

    def snapshot(self) -> dict[str, Any]:
        with _lock:
            return {
                "token_total": self.input + self.output,
                "token_input": self.input,
                "token_output": self.output,
                "token_calls": self.calls,
                "tokens_by_step": {k: v["total"] for k, v in self.by_step.items()},
            }


tracker = _Tracker()


def _extract_usage(response: LLMResult) -> tuple[int, int]:
    """Pull (input, output) token counts from an LLM response, provider-agnostic."""
    # Preferred: langchain-core's normalized usage_metadata on the message.
    try:
        for gens in response.generations:
            for gen in gens:
                msg = getattr(gen, "message", None)
                um = getattr(msg, "usage_metadata", None)
                if um:
                    return (
                        int(um.get("input_tokens", 0) or 0),
                        int(um.get("output_tokens", 0) or 0),
                    )
    except Exception:
        pass
    # Fallback: provider token_usage in llm_output (OpenAI / litellm style).
    try:
        out = response.llm_output or {}
        tu = out.get("token_usage") or out.get("usage") or {}
        inp = tu.get("prompt_tokens", tu.get("input_tokens", 0)) or 0
        outp = tu.get("completion_tokens", tu.get("output_tokens", 0)) or 0
        return int(inp), int(outp)
    except Exception:
        return 0, 0


class TokenUsageCallback(BaseCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        inp, out = _extract_usage(response)
        if inp or out:
            tracker.add(_current_step, inp, out)


token_callback = TokenUsageCallback()
