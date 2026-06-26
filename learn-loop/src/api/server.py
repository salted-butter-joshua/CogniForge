"""Uvicorn entrypoint for CogniForge Console."""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    host = os.getenv("CONSOLE_HOST", "0.0.0.0")
    port = int(os.getenv("CONSOLE_PORT", "8080"))
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=os.getenv("CONSOLE_RELOAD", "").lower() in ("1", "true"),
        log_level="info",
    )


if __name__ == "__main__":
    main()
