# 镜像部署（无需源码）

适用于服务器只跑容器、不克隆仓库的场景。使用 `ghcr.io/mcocdaa/siteflow` 发布镜像。

## 步骤

```bash
mkdir -p /root/workspace/siteflow && cd /root/workspace/siteflow
# 上传本目录的 init.sh、stop.sh、.env.example 后：
cp .env.example .env
vi .env                      # 设置 ADMIN_PASSWORD（必填）
chmod 600 .env
TAG=v1.0.0 ./init.sh         # 默认监听 127.0.0.1:8003
```

容器以 uid 1000 运行，`init.sh` 会自动把 `./data` 属主改为 1000:1000。

## 反向代理

nginx 参考 `nginx.conf.example`；HTTPS 终止在代理层，因此 `.env` 保持
`COOKIE_SECURE=true`。升级：修改 `TAG` 后重跑 `./init.sh`（数据在 `./data`，不受影响）。

## 真实验例

服务器 `mcocdaa-newapi.xin` 上的部署：`/root/workspace/siteflow/init.sh`，
反代 `siteflow.mcocdaa-newapi.xin` → `127.0.0.1:8003`。
