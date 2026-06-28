"""Node logging helpers — wrap graph nodes with structured step logs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from src.logging_config import log_step_done, log_step_start
from src.tools.token_tracker import set_current_step

F = TypeVar("F", bound=Callable[..., dict])


def logged_node(step: str) -> Callable[[F], F]:
    """Decorator: emit START/DONE for parent-graph nodes."""

    def decorator(fn: F) -> F:
        def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            log_step_start(state, step)
            set_current_step(step)
            result = fn(state, *args, **kwargs)
            log_step_done(state, step, result)
            return result

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper  # type: ignore[return-value]

    return decorator
