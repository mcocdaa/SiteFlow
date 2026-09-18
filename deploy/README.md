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

可覆盖的环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `TAG` | `v1.0.0` | 镜像版本 |
| `SITEFLOW_PORT` | `8003` | 宿主监听端口（仅本机） |
| `SITEFLOW_NAME` | `siteflow` | 容器名 |

## 说明

- 反向代理与 HTTPS 由部署者按自己的方案配置，本项目只负责容器。
- HTTPS 代理后 `.env` 保持 `COOKIE_SECURE=true`；纯本机调试可设 `false`。
- 升级：修改 `TAG` 后重跑 `./init.sh`（数据在 `./data`，不受影响）。
