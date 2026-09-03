#!/usr/bin/env bash
# 開発用の起動スクリプト
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

export PYTHONPATH="$(pwd)/src"
exec ./.venv/bin/uvicorn bcards.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
