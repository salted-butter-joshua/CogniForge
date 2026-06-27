"""Verify Python version before install."""

from __future__ import annotations

import sys

MIN_MAJOR, MIN_MINOR = 3, 9


def main() -> int:
    v = sys.version_info
    if (v.major, v.minor) < (MIN_MAJOR, MIN_MINOR):
        print(
            f"ERROR: Python {v.major}.{v.minor} is too old.\n"
            f"       Learn Loop requires Python >= {MIN_MAJOR}.{MIN_MINOR} "
            f"(langgraph 0.2.x).\n"
            f"       Current: {sys.executable}\n\n"
            f"Fix (conda):\n"
            f"  conda create -n learn-loop python=3.11 -y\n"
            f"  conda activate learn-loop\n"
            f"  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    print(f"OK: Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
