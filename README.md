# SiteFlow

> Docker 化轻量级个人作品收集与沙箱画廊展示平台（HTML / ZIP / 静态站点 / 外链）。

[![Family: *Flow](https://img.shields.io/badge/family-*Flow-8A2BE2.svg)](https://github.com/mcocdaa)
[![CI](https://github.com/mcocdaa/SiteFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/mcocdaa/SiteFlow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mcocdaa/SiteFlow)](https://github.com/mcocdaa/SiteFlow/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

Docker 化部署的个人作品收集与展示平台：单个管理员上传 HTML / ZIP 静态站点或添加外链，访客在画廊中浏览。设计细节见 [DESIGN.md](DESIGN.md)。

## 核心特性 (v2.2)

- **三类作品与多级空间**：单 HTML、ZIP 静态站点、外链（卡片 + 新标签跳转），支持最多 3 层嵌套空间；内置简历（JSON Resume 子集，可打印导出）与博客（CommonMark 严格安全渲染）。
- **沉浸式视口预览与真机联调**：站内模态框支持桌面端 (100%)、平板端 (768px)、手机端 (375px) 响应式视口无缝切换与横竖屏旋转，一键弹出局域网真机调试二维码。
- **全局命令面板 (Cmd+K / Ctrl+K)**：键盘快捷键呼出全站瞬时搜索与快捷动作（切换外观、直达管理台、项目模糊检索）。
- **多空间独立主题定制**：每个空间支持独立配置强调色（Accent Color）、字体风格（Sans/Serif/Mono）与卡片圆角，服务端动态注入作用域 CSS 变量。
- **项目一键密码锁**：支持单个项目设置访问密码，Argon2id 加密存储，成功解锁后签发 `Path=/projects/{slug}/` 强隔离鉴权 Cookie。
- **过程式动态网格矢量封面**：根据项目 Slug 自动生成确定性几何网格与技术徽章 SVG，告别纯色空白。
- **隐私优先本地访问统计**：当日 IP + UA 哈希匿名去重，管理后台展示今日/7天 PV/UV 及轻量平滑纯 SVG 趋势折线。
- **加固级 ZIP 解压引擎**：100:1 压缩比解压炸弹熔断防御、目录 Inode 数量保护、Windows ZIP (CP437/GBK) 智能无损转码。
- **分层静态缓存与子域名路由**：`index.html` 协商更新、静态资源 ETag + 304 快速响应；支持 `BASE_DOMAIN` 泛解析子域名无缝直连。
- **同域严格 CSP 沙箱**：作品以 `CSP: sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads` 不透明源渲染，无法触达管理员会话。
- **轻量单容器**：FastAPI + SQLite WAL 模式，内存占用通常 < 60MB，零前端打包依赖。

## 快速开始

```bash
cp .env.example .env        # 修改 ADMIN_PASSWORD
mkdir -p data && sudo chown -R 1000:1000 data
docker compose up -d --build
```

访问 `http://127.0.0.1:8000`（仅监听本机，由宿主反向代理对外）。管理员入口 `/login`。

服务器无源码部署（仅 `init.sh` + `.env`）见 [deploy/README.md](deploy/README.md)。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ADMIN_PASSWORD` | 无（必填） | 管理员密码；修改并重启后旧会话全部失效 |
| `SITE_TITLE` | `SiteFlow` | 站点标题 |
| `SITE_DESCRIPTION` | 一句默认描述 | 画廊副标题 |
| `MAX_UPLOAD_MB` | `100` | 上传大小上限 (MB) |
| `MAX_EXTRACT_MB` | `500` | 解压总大小上限 (MB) |
| `MAX_ZIP_ENTRIES` | `5000` | 单个压缩包最大条目数 |
| `COOKIE_SECURE` | `true` | HTTPS 部署保持 `true`；纯本机调试可设 `false` |
| `BASE_DOMAIN` | 空字符串 | 可选，泛解析子域名根域（如 `demo.company.com`） |
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
