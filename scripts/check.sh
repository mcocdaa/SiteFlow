#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"
uv lock --check
uv run --frozen --extra dev python scripts/check_repo.py
uv run --frozen --extra dev pytest -q
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev ruff format --check .
uv run --frozen --extra dev mypy app tests scripts/check_repo.py
for script in app/static/js/*.js; do
  node --check "$script"
done
echo "✓ 全部检查通过"
