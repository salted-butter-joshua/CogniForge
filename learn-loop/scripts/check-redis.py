"""Test Redis connectivity for local dev."""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from src.config import get_settings


def main() -> int:
    settings = get_settings()
    url = settings.redis_url
    print(f"REDIS_URL={url}")

    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=5)
        pong = client.ping()
        print(f"PING -> {pong}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Fix REDIS_URL in .env or check network/firewall to 10.101.15.5:6380", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
