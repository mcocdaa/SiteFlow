#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

docker compose -p siteflow -f "$PROJECT_ROOT/docker-compose.yml" down
echo "✓ 已停止 SiteFlow"
