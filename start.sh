#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

(cd "$ROOT/backend" && source .venv/bin/activate && uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8006) &
cd "$ROOT/frontend" && npm run dev
