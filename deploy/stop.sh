#!/usr/bin/env bash
set -euo pipefail
NAME="${SITEFLOW_NAME:-siteflow}"
docker rm -f "$NAME"
echo "✓ SiteFlow（${NAME}）已停止"
