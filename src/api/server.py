"""Uvicorn entrypoint for CogniForge Console."""

from __future__ import annotations

import os
import sys

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    host = os.getenv("CONSOLE_HOST", "127.0.0.1")
    port = int(os.getenv("CONSOLE_PORT", "8080"))

    # Fail fast with a clear message before uvicorn binds the port.
    try:
        import langgraph  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "ERROR: langgraph is not installed for this Python interpreter.\n"
            f"  Python: {sys.executable}\n"
            "  Fix: conda activate learn-loop && pip install -r requirements.txt"
        ) from exc

    from src.config import get_settings
    from src.models.router import validate_api_keys

    ok, err = validate_api_keys(get_settings())
    if not ok:
        print(f"WARNING: {err}", file=sys.stderr)
        print(
            "  Create .env from .env.example and set MINIMAX_API_KEY (or another provider key).",
            file=sys.stderr,
        )

    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=os.getenv("CONSOLE_RELOAD", "").lower() in ("1", "true"),
        log_level="info",
    )


if __name__ == "__main__":
    main()
