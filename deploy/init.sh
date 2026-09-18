#!/usr/bin/env bash
# SiteFlow 镜像部署（无需克隆源码）
# 用法: TAG=v1.0.0 SITEFLOW_PORT=8003 ./init.sh
set -euo pipefail

TAG="${TAG:-v1.0.0}"
PORT="${SITEFLOW_PORT:-8003}"
IMAGE="ghcr.io/mcocdaa/siteflow:${TAG}"

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "[init] 已创建 .env，请设置 ADMIN_PASSWORD 后重试" >&2
    exit 1
fi
if grep -q '^ADMIN_PASSWORD=change-me$' .env; then
    echo "[error] 请先修改 .env 中的 ADMIN_PASSWORD" >&2
    exit 1
fi

mkdir -p data
chown 1000:1000 data
chmod 0750 data

docker pull "$IMAGE"
docker rm -f siteflow >/dev/null 2>&1 || true
docker run -d --name siteflow --restart unless-stopped \
    -p "127.0.0.1:${PORT}:8000" \
    -v "$PWD/data:/data" \
    --env-file ./.env \
    "$IMAGE"

echo "✓ SiteFlow 已启动: 127.0.0.1:${PORT}（管理员入口 /login）"
