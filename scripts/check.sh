#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

cd "$PROJECT_ROOT"
"$PYTHON" -m pytest -q
"$PYTHON" -m ruff check app tests
"$PYTHON" -m mypy app tests
node --check app/static/js/admin.js
echo "✓ 全部检查通过"
