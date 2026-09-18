# 部署

## 前置

- Docker 与 docker compose
- 宿主机准备数据目录：`mkdir -p data`

## 步骤

```bash
cp .env.example .env       # 设置 ADMIN_PASSWORD（必填）
./scripts/start.sh         # 等价于 docker compose up -d --build
```

默认仅监听 `127.0.0.1:8000`，由宿主反向代理对外提供 HTTPS。

## 反向代理

nginx：

```nginx
server {
    listen 443 ssl;
    server_name xxx.example.com;

    client_max_body_size 120m;   # 需大于 MAX_UPLOAD_MB
    proxy_read_timeout 300s;     # ZIP 解压可能较慢

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Caddy：

```caddyfile
xxx.example.com {
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 120MB
    }
}
```

HTTPS 部署时保持 `COOKIE_SECURE=true`（默认）；纯本机 HTTP 调试才设 `false`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ADMIN_PASSWORD` | 无（必填） | 修改后重启，旧会话立即失效 |
| `SITE_TITLE` | `SiteFlow` | 站点标题 |
| `SITE_DESCRIPTION` | 内置描述 | 画廊副标题 |
| `MAX_UPLOAD_MB` | `100` | 上传大小上限 |
| `MAX_EXTRACT_MB` | `500` | ZIP 解压后总大小上限 |
| `MAX_ZIP_ENTRIES` | `5000` | ZIP 条目数上限 |
| `COOKIE_SECURE` | `true` | HTTPS 部署保持 true |
| `DATA_DIR` | `/data` | 容器内数据目录（挂载卷） |
| `PROJECTS_SANDBOX` | `true` | 禁止关闭，同域部署必须保持隔离 |

## 镜像部署（服务器无源码）

只需 `init.sh` + `.env`，不克隆仓库，详见 [deploy/README.md](../deploy/README.md)：

```bash
cp deploy/.env.example deploy/.env    # 设置 ADMIN_PASSWORD
cd deploy && TAG=v1.0.0 ./init.sh     # 默认监听 127.0.0.1:8003
```

反向代理与 HTTPS 由部署者自行配置，容器只监听 `127.0.0.1`。
