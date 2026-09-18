# SiteFlow

[![CI](https://github.com/mcocdaa/SiteFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/mcocdaa/SiteFlow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mcocdaa/SiteFlow)](https://github.com/mcocdaa/SiteFlow/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

Docker 化部署的个人作品收集与展示平台：单个管理员上传 HTML / ZIP 静态站点或添加外链，访客在画廊中浏览。设计细节见 [DESIGN.md](DESIGN.md)。

## 功能

- 三类作品：单 HTML、ZIP 静态站点（站内全屏查看）、外链（卡片 + 新标签跳转）
- 卡片画廊：响应式网格、跟随系统深色模式、无构建无 CDN
- 管理台：拖拽上传、链接 OG 自动填充、封面、Pin、上移/下移、显隐、删除
- 安全隔离：作品以 `CSP: sandbox` 不透明源渲染，无法触达管理会话与内部 API
- 单容器：FastAPI + SQLite + 本地文件，数据全部落在挂载卷

## 快速开始

```bash
cp .env.example .env        # 修改 ADMIN_PASSWORD
mkdir -p data && sudo chown -R 1000:1000 data
docker compose up -d --build
```

访问 `http://127.0.0.1:8000`（仅监听本机，由宿主反向代理对外）。管理员入口 `/login`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ADMIN_PASSWORD` | 无（必填） | 管理员密码；修改并重启后旧会话全部失效 |
| `SITE_TITLE` | `SiteFlow` | 站点标题 |
| `SITE_DESCRIPTION` | 一句默认描述 | 画廊副标题 |
| `MAX_UPLOAD_MB` | `100` | 上传大小上限 |
| `COOKIE_SECURE` | `true` | HTTPS 部署保持 `true`；纯本机调试可设 `false` |
| `DATA_DIR` | `/data` | 数据目录（DB、作品文件、封面） |
| `PROJECTS_SANDBOX` | `true` | 禁止关闭；同域部署必须保持 sandbox 隔离 |

## 反向代理

nginx 示例：

```nginx
server {
    listen 443 ssl;
    server_name xxx.example.com;

    client_max_body_size 120m;   # 大于 MAX_UPLOAD_MB
    proxy_read_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 本地开发

协作与安全约定见 [AGENTS.md](AGENTS.md)。

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ADMIN_PASSWORD=dev DATA_DIR=./data COOKIE_SECURE=false \
  uvicorn app.main:app --reload --port 8000
```

检查与测试：

```bash
pytest -q
ruff check app tests
mypy app tests
```

## 数据与备份

数据目录结构：

```
data/
├── siteflow.db            # SQLite（WAL）
├── secret_key             # 会话签名密钥
├── projects/{slug}/...    # 作品原始文件
└── media/covers/*.webp    # 封面
```

备份整个 `data/` 目录即可；升级镜像不触碰卷。
