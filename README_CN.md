<div align="center">

# SiteFlow

面向 HTML 报告、静态站点与 AI 评测制品的轻量级安全沙箱画廊与无头部署门户。

[![Family: *Flow](https://img.shields.io/badge/family-*Flow-8A2BE2.svg)](https://github.com/mcocdaa)
[![CI](https://github.com/mcocdaa/SiteFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/mcocdaa/SiteFlow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mcocdaa/SiteFlow)](https://github.com/mcocdaa/SiteFlow/releases)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) · [简体中文](README_CN.md)

<img src="docs/assets/demo_siteflow.gif" alt="SiteFlow Demo" width="840">

</div>

## ✨ 核心特性

- **Human via UI, AI via API**：既为人类提供直观的拖拽管理后台，又为 AI Agent 与 CI/CD 流水线提供幂等的 `PUT /api/admin/projects/{slug}/deploy` 一键无头发布接口。
- **零信任 CSP 沙箱与解压炸弹防御**：作品在同域下通过严格不透明源 CSP 沙箱（`allow-scripts` 强隔离管理员会话 Cookie）渲染，内置 100:1 压缩比熔断、Inode 上限保护与 Windows ZIP（CP437/GBK）智能无损转码。
- **多级嵌套空间与独立主题**：支持单 HTML、ZIP 静态站点、外链、在线简历与 CommonMark 博客，最多 3 层空间嵌套，每个空间可独立定制强调色、字体（`Sans` / `Serif` / `Mono`）与卡片圆角。
- **响应式视口预览与 `Cmd+K` 命令面板**：站内模态框支持桌面（`100%`）、平板（`768px`）、手机（`375px`）视口切换、横竖屏旋转与局域网真机调试二维码，搭配 `Cmd+K` / `Ctrl+K` 全局瞬时检索。
- **过程式矢量封面、密码锁与趋势折线**：按 Slug 确定性生成几何网格 SVG/WebP 封面，支持单项目 Argon2id 独立密码锁（签发 `Path=/projects/{slug}/` 隔离 Cookie）及隐私优先的 7 天 PV/UV 纯 SVG 趋势折线。
- **极简轻量单容器**：FastAPI + SQLite WAL 架构，常驻内存 < 60MB，支持静态资源 ETag/304 协商缓存与 `BASE_DOMAIN` 泛解析子域名直连。

## 🚀 快速开始

**方式 1 — Docker Compose（推荐）**

```bash
cp .env.example .env   # 设置管理员密码 ADMIN_PASSWORD
docker compose up -d --build
```

打开 `http://127.0.0.1:8000`（管理后台：`/admin`）。

**方式 2 — 本地 `uv` 启动**

```bash
ADMIN_PASSWORD=dev COOKIE_SECURE=false uv run uvicorn app.main:app --port 8000
```

## 🤖 AI 一键发布接口

AI Agent 或自动化脚本可通过 `SITEFLOW_API_TOKEN`（可在 `.env` 中显式配置，或由系统基于 `ADMIN_PASSWORD` 自动派生）幂等地创建或更新单文件 HTML 报告与多文件 ZIP 站点：

```bash
# 一键部署或覆盖更新静态 HTML 报告 / ZIP 站点
curl -X PUT http://127.0.0.1:8000/api/admin/projects/my-report/deploy \
  -H "Authorization: Bearer <SITEFLOW_API_TOKEN>" \
  -F "file=@./report.html" \
  -F "title=Eval Benchmark Report" \
  -F "description=Nightly automated run"

# 查询已部署项目列表与元数据
curl -H "Authorization: Bearer <SITEFLOW_API_TOKEN>" \
  http://127.0.0.1:8000/api/admin/projects
```

## ⚙️ 配置与文档

架构设计与安全边界详见 [DESIGN.md](DESIGN.md)，服务器免源码一键部署详见 [deploy/README.md](deploy/README.md)。

<details>
<summary>环境变量与 Nginx 反向代理配置</summary>

### 环境变量（`.env`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ADMIN_PASSWORD` | *（必填）* | 管理员密码；修改并重启后旧会话全部失效 |
| `SITEFLOW_API_TOKEN` | *（自动派生）* | 可选显式指定无头部署 API 的 Bearer Token |
| `SITE_TITLE` | `SiteFlow` | 画廊站点标题 |
| `SITE_DESCRIPTION` | 默认副标题 | 画廊副标题描述 |
| `MAX_UPLOAD_MB` | `100` | 单次上传文件大小上限 (MB) |
| `MAX_EXTRACT_MB` | `500` | 解压后总大小上限 (MB) |
| `MAX_ZIP_ENTRIES` | `5000` | 单个压缩包最大文件条目数 |
| `COOKIE_SECURE` | `true` | HTTPS 部署保持 `true`；纯本机 HTTP 调试可设 `false` |
| `BASE_DOMAIN` | `""` | 可选泛解析子域名根域（如 `demo.example.com`） |
| `DATA_DIR` | `/data` | 数据持久化目录（SQLite WAL、作品文件、封面） |
| `PROJECTS_SANDBOX` | `true` | 禁止关闭；同域部署必须保持沙箱隔离 |

### Nginx 反向代理

```nginx
server {
    listen 443 ssl;
    server_name gallery.example.com;

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

</details>

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。
