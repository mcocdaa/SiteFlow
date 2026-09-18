#!/usr/bin/env bash
# SiteFlow 启动脚本
# 用法:
#   ./scripts/start.sh          # Docker 部署（默认）
#   ./scripts/start.sh local    # 本地开发（uvicorn --reload）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

init_env() {
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        echo "[init] 已从 .env.example 创建 .env，请修改 ADMIN_PASSWORD 后重试"
        exit 1
    fi
    if grep -q '^ADMIN_PASSWORD=change-me$' "$PROJECT_ROOT/.env"; then
        echo "[error] 请先在 .env 中设置 ADMIN_PASSWORD"
        exit 1
    fi
}

run_docker() {
    mkdir -p "$PROJECT_ROOT/data"
    docker compose -p siteflow -f "$PROJECT_ROOT/docker-compose.yml" up -d --build
    echo "✓ 已启动: http://127.0.0.1:8000 （管理员入口 /login）"
}

run_local() {
    if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
        python3 -m venv "$PROJECT_ROOT/.venv"
        "$PROJECT_ROOT/.venv/bin/pip" install -q -r "$PROJECT_ROOT/requirements-dev.txt"
    fi
    set -a
    # shellcheck disable=SC1091
    . "$PROJECT_ROOT/.env"
    set +a
    cd "$PROJECT_ROOT"
    exec "$PROJECT_ROOT/.venv/bin/uvicorn" app.main:app --reload --port "${PORT:-8000}"
}

case "${1:-docker}" in
    docker)
        init_env
        run_docker
        ;;
    local)
        init_env
        run_local
        ;;
    *)
        echo "用法: $0 [docker|local]"
        exit 1
        ;;
esac
