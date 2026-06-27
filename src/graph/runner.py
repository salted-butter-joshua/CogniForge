"""Run LangGraph with Ctrl+C / SIGTERM cancellation between steps."""

from __future__ import annotations

import logging
import os
import signal
from typing import Any

from src.logging_config import get_loop_logger, log_finish

_cancel_requested = False
_force_exit = False


def _handle_cancel(signum: int, frame: Any) -> None:
    global _cancel_requested, _force_exit
    if _cancel_requested or _force_exit:
        log_finish("forced exit", level=logging.ERROR)
        os._exit(130)
    _cancel_requested = True
    log_finish("interrupt received; stop after current step (Ctrl+C again to force quit)", level=logging.WARNING)


def install_cancel_handlers() -> None:
    signal.signal(signal.SIGINT, _handle_cancel)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_cancel)


def reset_cancel_state() -> None:
    global _cancel_requested, _force_exit
    _cancel_requested = False
    _force_exit = False


def request_cancel() -> None:
    """Cooperative cancel (API / UI stop button)."""
    global _cancel_requested
    _cancel_requested = True


def is_cancel_requested() -> bool:
    return _cancel_requested


def run_graph_streaming(app: Any, init_state: dict, config: dict) -> dict:
    """Execute graph step-by-step so SIGINT can stop between nodes."""
    install_cancel_handlers()
    reset_cancel_state()
    result: dict = dict(init_state)
    try:
        for state in app.stream(init_state, config=config, stream_mode="values"):
            if _cancel_requested:
                raise KeyboardInterrupt
            if isinstance(state, dict):
                result = state
    except KeyboardInterrupt:
        raise

    return result
