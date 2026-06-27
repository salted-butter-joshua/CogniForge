#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — run: cp .env.local.example .env"
  exit 1
fi

export PYTHONPATH="$ROOT"

python scripts/check-python.py || exit 1

if [[ ! -d .venv ]]; then
  echo "Create venv with Python 3.9+ first, e.g.:"
  echo "  conda create -n learn-loop python=3.11 -y && conda activate learn-loop"
  echo "  python -m venv .venv"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q -r requirements.txt

echo "==> Checking Redis..."
python scripts/check-redis.py

echo "==> Starting Learn Loop..."
python -m src.main "$@"
