# SiteFlow 设计文档

> 一个自托管的作品展示应用：单管理员上传 HTML / ZIP / 外链，公开画廊以卡片形式展示作品。
> 设计原则：**简洁、直接、好看、大气**。

---

## 1. 背景与目标

### 1.1 背景

SiteFlow 是一个 Docker 化部署的个人作品收集与展示平台。管理员可以把三类内容作为"作品"发布：

| 类型 | 输入 | 展示方式 |
|------|------|----------|
| `html` | 单个 HTML 文件 | 站内打开，全屏查看 |
| `zip` | 静态站点压缩包 | 站内打开，全屏查看 |
| `link` | 外部超链接 | 卡片 + 点击新标签跳转外站 |

### 1.2 目标

- **极简部署**：`docker compose up -d` 即可运行，单容器（FastAPI + SQLite + 本地文件），数据落在挂载卷。
- **极简使用**：单管理员密码登录，拖拽上传即发布，无需构建、无需配置数据库。
- **好看的画廊**：卡片网格、大量留白、单一强调色、跟随系统深色模式。
- **安全展示**：上传的 HTML 可执行任意 JS，必须与主站隔离，不能威胁管理员会话。

### 1.3 非目标（v1 明确不做）

- 多用户 / 注册 / 权限系统
- 标签、搜索、分类
- 浏览量统计与分析
- 回收站、版本历史
- 拖拽排序（用上移/下移按钮替代）
- 对象存储（S3 等）、CDN
- 页面构建步骤（无 npm、无 CDN，纯服务端模板 + 手写 CSS）

---

## 2. 角色与核心流程

### 2.1 管理员

1. 访问 `/login`，输入 `ADMIN_PASSWORD` 对应密码。
2. 进入 `/admin`：拖拽上传 `.html` 或 `.zip`，或粘贴外链添加作品。
3. 编辑元数据（标题、描述、封面）、Pin 置顶、上移/下移、显隐、删除。
4. 画廊 `/` 即时反映改动（服务端渲染，无缓存）。

### 2.2 访客

1. 打开 `/`，看到作品卡片网格。
2. 点击 `html` / `zip` 作品 → 进入 `/projects/{slug}/` 全屏查看。
3. 点击 `link` 作品 → 新标签打开外站。
4. 隐藏（`visible=0`）的作品对访客不可见，直接访问返回 404。

---

## 3. 整体架构

```
        访客 / 管理员
             │  HTTPS
             ▼
   用户自备反向代理 (nginx / Caddy)
             │  HTTP 127.0.0.1:8000
             ▼
   ┌─────────────────────────────────────┐
   │  容器 siteflow ( 非 root, uid 1000 ) │
   │                                     │
   │  FastAPI + Jinja2 + 手写 CSS/JS     │
   │        │                            │
   │        ├── SQLite  /data/siteflow.db│
   │        ├── 作品文件 /data/projects/  │
   │        ├── 封面    /data/media/      │
   │        └── 密钥    /data/secret_key  │
   └─────────────────────────────────────┘
             │
        /data 挂载卷（宿主机目录）
```

- 单进程 uvicorn，单容器，SQLite 单写入者模型与单管理员场景完全匹配。
- 应用不处理 TLS，由用户反代负责；应用信任 `X-Forwarded-*`（`--proxy-headers`）。
- 画廊与作品同域不同路径（`/` 与 `/projects/`），安全依赖响应头隔离（见第 7 节）。

---

## 4. 数据模型

SQLite，WAL 模式，`foreign_keys=ON`，`busy_timeout=5000`。

### 4.1 `projects` 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `slug` | TEXT UNIQUE NOT NULL | URL 标识，创建后不可变 |
| `type` | TEXT NOT NULL | `html` / `zip` / `link`（CHECK 约束） |
| `title` | TEXT NOT NULL | 卡片标题 |
| `description` | TEXT NOT NULL DEFAULT '' | 一句话描述，卡片上最多 2 行 |
| `url` | TEXT NULL | 仅 `link` 类型，必须 http/https |
| `entry` | TEXT NULL | 站内作品的入口文件相对路径，如 `index.html` 或 `dist/index.html` |
| `cover` | TEXT NULL | 封面相对路径，如 `covers/{slug}.webp` |
| `pinned` | INTEGER NOT NULL DEFAULT 0 | 0/1，置顶 |
| `sort_order` | INTEGER NOT NULL DEFAULT 0 | 手动排序，越小越靠前 |
| `visible` | INTEGER NOT NULL DEFAULT 1 | 0/1，访客是否可见 |
| `created_at` | TEXT (ISO8601) | 创建时间 |
| `updated_at` | TEXT (ISO8601) | 更新时间 |

**排序规则**（画廊查询）：

```sql
ORDER BY pinned DESC, sort_order ASC, created_at DESC
```

**slug 生成**：由标题转小写 ASCII，仅保留 `[a-z0-9-]`，折叠连续连字符；标题为中文等非 ASCII 时回退为 `work-{6位随机}`。冲突时追加 `-2`、`-3`。区分大小写无关，创建后永不修改（避免旧链接失效）。

**上移/下移语义**：只与**同组**（同为 pinned 或同为普通）的前/后邻居交换 `sort_order`，不会跨越置顶边界。

### 4.2 `admin` 表（单行）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 恒为 1 |
| `password_hash` | TEXT | argon2 哈希 |
| `updated_at` | TEXT | 最后同步时间 |

**启动时同步**：每次启动读取 `ADMIN_PASSWORD`，用 argon2 重新哈希并覆盖写入。改环境变量 = 改密码，无"忘记密码"流程。`ADMIN_PASSWORD` 缺失时应用拒绝启动并打印明确错误。

---

## 5. 路由与 API

### 5.1 公开页面

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 画廊：卡片网格，只显示 `visible=1` |
| GET | `/projects/{slug}/` | 302 跳转到该作品的 `entry` 文件（保持相对资源路径可用） |
| GET | `/projects/{slug}/{path}` | 静态文件服务（含安全校验，见 7.3） |
| GET | `/media/covers/{name}` | 封面图 |
| GET | `/healthz` | 健康检查，返回 `{"status":"ok"}` |
| GET | `/login` | 登录页 |
| POST | `/login` | 校验密码，建会话；失败计入限流 |
| POST | `/logout` | 销毁会话 |

### 5.2 管理页面与 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin` | 管理台页面（列表 + 上传区 + 编辑面板） |
| POST | `/api/admin/projects/upload` | multipart：`file` + 可选 `title`/`description`；按扩展名分流 html/zip |
| POST | `/api/admin/projects/link` | JSON：`url` + 可选 `title`/`description`；抓 OG 元数据 |
| PATCH | `/api/admin/projects/{id}` | JSON：`title` / `description` / `pinned` / `visible` / `sort_order` / `url` |
| POST | `/api/admin/projects/{id}/cover` | multipart 图片，替换封面 |
| DELETE | `/api/admin/projects/{id}` | 硬删除（DB 行 + 作品目录 + 封面文件） |

- 所有 `/api/admin/*` 与 `/admin` 要求有效会话。
- 所有**写操作**额外要求：`X-CSRF-Token` 头与会话内 token 一致，且校验 `Origin`/`Host` 同源。
- 管理页面响应 `Cache-Control: no-store`。
- 返回格式统一 JSON：成功 `{"ok":true,...}`；失败 `{"ok":false,"error":"..."}` + 合适状态码。

---

## 6. 上传处理管线

### 6.1 HTML

1. 校验扩展名 `.html` / `.htm`，大小 ≤ `MAX_UPLOAD_MB`。
2. 以二进制流式写入 `data/projects/{slug}/index.html`，`entry = index.html`。
3. 文件名不可信，忽略原始文件名。

### 6.2 ZIP

1. 流式落盘到 `data/tmp/{random}.zip`（不占内存），超限立即中断并清理。
2. **Zip Slip 防护**：逐个 entry 规范化路径后校验——拒绝绝对路径、`..`、Windows 盘符、反斜杠转义；拒绝符号链接 entry（检查 external_attr 文件类型位）。
3. **Zip 炸弹防护**：解压前检查 entry 数 ≤ `MAX_ZIP_ENTRIES`（默认 5000）、解压总量 ≤ `MAX_EXTRACT_MB`（默认 500）；解压过程中再次累计校验，超限即中止并清理整个作品目录。
4. 解压时跳过 `__MACOSX/`、`.DS_Store`、点开头文件。
5. **中文文件名兼容**：ZIP 未声明 UTF-8 标志时 Python 按 cp437 解码，对结果做 best-effort 重解码（cp437 → gbk）修复乱码。
6. **入口定位**（按优先级）：
   - 根目录存在 `index.html`（大小写不敏感）→ 用它；
   - 若只有一个顶层目录 → 进入该目录重复上一步；
   - 否则选全包中层级最浅的 `index.html`；
   - 一个都找不到 → 422 错误"ZIP 中未找到 index.html"，删除临时文件与半成品目录。
7. `entry` 存相对路径（如 `dist/index.html`），保证 `/projects/{slug}/` 跳转后相对路径仍正确。

### 6.3 链接

1. 校验 URL：必须是 `http` / `https`，长度 ≤ 2048。
2. 抓取页面（超时 5s，HTML 上限 512KB），解析 `og:title` / `og:description` / `og:image`，回退 `<title>`；标题再回退为域名。
3. `og:image` 下载（上限 5MB）→ Pillow 转 webp 缩略图存 `/media/covers/{slug}.webp`；失败不阻塞创建，改用占位封面。
4. 抓取失败（超时、403 等）同样不阻塞，作品照常创建，元数据留空由管理员补。

### 6.4 封面（手动）

- 接受 jpg / png / webp / gif（取首帧），≤ 10MB。
- Pillow 校验真实格式（不信任 MIME/扩展名）+ 重新编码为 webp（最长边 1600px，quality 82），**剥离 EXIF**（含 GPS）。
- 存储 `/media/covers/{slug}.webp`，替换时删除旧文件。
- 无封面时由前端渲染占位：由 slug 哈希决定色相的柔和渐变 + 标题首字符（零存储、零请求）。

---

## 7. 安全模型

### 7.1 核心威胁与对策

上传的 HTML/ZIP 是**任意可执行内容**，与主站同源（仅有路径差异，路径不构成 origin 边界）。若不处理，作品页 JS 可以：

- 读取管理员会话 Cookie（HttpOnly 可挡读取，但同源 `fetch` 会自动带 Cookie）；
- 直接调用 `/api/admin/*` 冒充管理员（配合 CSRF token 是否可被读到？同源文档可读 DOM 内嵌 token，故必须更彻底地隔离）；
- 顶部导航钓鱼等。

### 7.2 对策：`/projects/` 全量 CSP sandbox（关键设计）

对 `/projects/` 前缀下的**每一个响应**（中间件统一注入）添加：

```
Content-Security-Policy: sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads
```

效果：浏览器把该文档（**即使顶层直接打开**）放入**不透明源（opaque origin）**：

- 读不到本站 Cookie、localStorage、IndexedDB；
- 发往本站的 `fetch` 视为跨源且不带凭证，响应无 CORS 头 → 被拦截；
- 不能顶层导航、不能跳出沙箱。

正常静态站点不受影响：`<script src>`、`<img>`、CSS、字体等标签加载不是 CORS 受限请求；内联脚本照常执行。**已知代价**：作品自身 JS 用 `fetch()`/`XHR` 读取同目录资源会被 CORS 拦截（因为源已不透明），少数 SPA 或依赖运行时拉取数据的静态站会受影响。

通过 `PROJECTS_SANDBOX` 开关（默认 `true`）控制。未来若把 `/projects/` 放到独立子域（如 `p.example.com`），跨域天然隔离，可关闭该头以恢复完整 fetch 能力。

同时在 `/projects/` 响应上附加：`X-Content-Type-Options: nosniff`；不设置 `X-Frame-Options`（避免防碍未来站内 iframe 预览方案）。

### 7.3 静态文件服务校验

- 用 `realpath` 解析后校验目标必须位于该作品的目录内（防路径穿越、防符号链接逃逸）。
- 拒绝任何点开头的路径段（`.git`、`.env`、`.htaccess` 等）。
- 不提供目录列表；`/projects/{slug}/` 只做 302 到 entry。
- HTML 响应 `Content-Type: text/html; charset=utf-8`；按扩展名映射 MIME，未知类型 `application/octet-stream`。
- 不可见作品（`visible=0`）对访客 404。

### 7.4 会话与 CSRF

- 会话：`itsdangerous` 签名 Cookie，载荷含 `admin_id`、`csrf`、签发/过期时间；有效期 7 天；`HttpOnly`、`SameSite=Lax`、`Secure`（`COOKIE_SECURE=true` 默认，纯 HTTP 本地调试可设 `false`）。
- 签名密钥：优先 `SECRET_KEY` env；未提供时首启生成随机密钥持久化到 `/data/secret_key`（重启会话不失效）。
- CSRF：写操作要求自定义头 `X-CSRF-Token`（跨站表单无法携带），并校验 `Origin` 与 `Host` 同源；`SameSite=Lax` 作为第二层。
- 登录限流：内存滑动窗口，按客户端 IP 15 分钟内失败 5 次 → 429；成功后清零。IP 从 `X-Forwarded-For` 取（仅信任反代，`FORWARDED_ALLOW_IPS` 由 compose 配置）。
- 密码校验使用 `hmac.compare_digest` 风格恒时比较（argon2 验证天然覆盖）。

### 7.5 上传面

- 只接受 `.html` / `.htm` / `.zip` 与封面图片格式；大小/数量限制见配置表。
- ZIP 全部安全处理见 6.2；任何一步失败都清理临时文件与半成品目录。
- OG 抓取为管理员主动发起，SSRF 风险由"只有管理员可用"兜底；仍设置超时和响应大小上限。

---

## 8. 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ADMIN_PASSWORD` | 无（必填） | 管理员密码，缺失则拒绝启动 |
| `SECRET_KEY` | 自动生成 | 会话签名密钥；未设置时持久化到 `/data/secret_key` |
| `DATA_DIR` | `/data` | 数据根目录 |
| `MAX_UPLOAD_MB` | `100` | 上传文件大小上限 |
| `MAX_EXTRACT_MB` | `500` | ZIP 解压总量上限 |
| `MAX_ZIP_ENTRIES` | `5000` | ZIP 文件条目数上限 |
| `PROJECTS_SANDBOX` | `true` | 是否给 `/projects/` 注入 CSP sandbox 头 |
| `COOKIE_SECURE` | `true` | 会话 Cookie 加 Secure；纯 HTTP 调试设 `false` |
| `SITE_TITLE` | `SiteFlow` | 画廊站名（页头与标题） |
| `SITE_DESCRIPTION` | 空 | 画廊副标题/页脚一句话 |
| `SITE_URL` | 空 | 用于 OG/绝对链接（可留空） |
| `PORT` | `8000` | 监听端口 |
| `LOG_LEVEL` | `info` | 日志级别 |
| `FORWARDED_ALLOW_IPS` | `*` | 信任的反代来源（compose 内网，固定为容器网络） |

---

## 9. 前端与视觉设计语言

### 9.1 原则

- 无边框、少阴影、大留白、单一强调色；内容优先，界面退后。
- 系统字体栈：`-apple-system, "Segoe UI", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif`。
- 无构建步骤：一个 `app.css` + 少量原生 JS（管理台交互），无任何第三方 CDN 资源（离线可用）。

### 9.2 设计 Token（CSS 自定义属性）

| Token | 浅色 | 深色（`prefers-color-scheme: dark`） |
|-------|------|--------------------------------------|
| `--bg` | `#fafafa` | `#0f1115` |
| `--surface` | `#ffffff` | `#171a21` |
| `--text` | `#1a1d23` | `#e8eaed` |
| `--text-muted` | `#6b7280` | `#9aa1ac` |
| `--accent` | `#4f46e5`（靛蓝） | 同色提亮 `#818cf8` |
| `--border` | `#e5e7eb` | `#262b36` |
| `--radius-card` | `14px` | 同 |
| `--radius-btn` | `9px` | 同 |
| `--shadow-hover` | `0 8px 24px rgba(0,0,0,.08)` | `0 8px 24px rgba(0,0,0,.4)` |

间距以 4px 为基础栅格（4/8/12/16/24/32/48/64）。

### 9.3 画廊页 `/`

- 页头：站名（粗体、左）+ 极小的管理入口图标（右）。
- 网格：`repeat(auto-fill, minmax(280px, 1fr))`，间距 32px；移动端单列。
- 卡片结构（自上而下）：
  1. 封面区：16:10，圆角，`object-fit: cover`；无封面时渲染占位（slug 哈希取色相的柔和渐变 + 标题首字符，白色 80% 透明度、约 48px）；
  2. 标题：16–18px、600 字重，最多 1 行省略；
  3. 描述：14px、`--text-muted`，最多 2 行省略；
  4. 元信息行：类型角标（`HTML` / `ZIP` / `LINK`，极小号、描边胶囊）+ 置顶作品的 pin 图标。
- 悬停：`translateY(-2px)` + `--shadow-hover`，过渡 150ms。
- 空状态：居中一行灰色文案 + （管理员登录时）引导去 `/admin` 上传。
- 点击行为：`html`/`zip` → `/projects/{slug}/`；`link` → 新标签打开外站（卡片右上角带外链箭头）。

### 9.4 管理台 `/admin`

- 与画廊同一设计语言，密度略高：
  - 顶部：拖拽上传区（虚线圆角框，拖入高亮）、"添加链接"输入行；
  - 列表：每行 = 缩略图 + 标题/描述 + 操作（编辑、Pin、上移、下移、显隐、删除）；
  - 编辑面板：右侧抽屉或行内展开，保存走 `PATCH`；
  - 上传用 `XMLHttpRequest` 显示进度（ZIP 解压期间显示处理中状态）。
- 删除有确认对话框（原生 `confirm` 即可，不引入组件库）。
- 原生 JS 单文件 `admin.js`，以 `data-*` 属性绑定行为，预计数百行以内。

### 9.5 登录页 `/login`

- 居中卡片，仅密码输入 + 按钮；错误提示行内展示；不做多余元素。

---

## 10. 目录结构

```
SiteFlow/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 实例、安全响应头中间件、路由挂载
│   ├── config.py            # 环境变量解析与校验
│   ├── models.py            # SQLAlchemy 模型
│   ├── store.py             # engine/session、PRAGMA、建表与全部查询/排序
│   ├── auth.py              # 会话、CSRF、限流、密码校验与失效
│   ├── deps.py              # DbSession / AdminConfig 依赖、api_error
│   ├── routes.py            # 聚合 router（views + admin）
│   ├── views.py             # /、/projects/*、/media/*、/login、/logout、/healthz
│   ├── admin.py             # /admin、/api/admin/*
│   ├── uploads.py           # ZIP 安全解压、封面处理、清理
│   ├── og.py                # Open Graph 与封面图抓取（含私网校验）
│   ├── templating.py        # Jinja2 环境
│   ├── templates/           # gallery.html, login.html, admin.html
│   └── static/
│       ├── css/app.css
│       ├── img/placeholder.svg
│       └── js/admin.js
├── tests/                   # pytest（smoke / flow / security）
├── .opencode/skills/        # siteflow-dev 项目 skill
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── AGENTS.md
├── DESIGN.md
└── README.md
```

数据目录（挂载卷）：

```
/data/
├── siteflow.db
├── secret_key
├── tmp/
├── projects/{slug}/...      # 作品原始文件
└── media/covers/{slug}.webp # 封面
```

---

## 11. 部署

### 11.1 Dockerfile（要点）

- 基础镜像 `python:3.12-slim`；创建非 root 用户 `app`（uid 1000）。
- `pip install --no-cache-dir -r requirements.txt`（fastapi、uvicorn、sqlalchemy、jinja2、python-multipart、itsdangerous、argon2-cffi、pillow、httpx）。
- 复制 `app/`，`EXPOSE 8000`。
- `HEALTHCHECK` 用 `python -c` 请求 `/healthz`（避免装 curl）。
- 启动：`uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers`。

### 11.2 docker-compose.yml（要点）

```yaml
services:
  siteflow:
    build: .
    container_name: siteflow
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"          # 仅本机，由宿主反代对外
    environment:
      ADMIN_PASSWORD: "${ADMIN_PASSWORD:?please set ADMIN_PASSWORD}"
      SITE_TITLE: "My Works"
      MAX_UPLOAD_MB: "100"
    volumes:
      - ./data:/data
```

- 宿主机先 `mkdir -p data && sudo chown -R 1000:1000 data`（容器以 uid 1000 运行）。
- 升级：`docker compose pull && up -d` 或本地 `build --pull`；数据全在 `./data`。

### 11.3 反向代理示例

nginx：

```nginx
server {
    listen 443 ssl;
    server_name xxx.example.com;

    client_max_body_size 120m;      # 大于 MAX_UPLOAD_MB
    proxy_read_timeout 300s;        # ZIP 解压可能较慢

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

无需为 `/projects/` 单独配置——同一应用进程处理。

---

## 12. 验收标准

- [ ] `docker compose up -d` 后 `/healthz` 返回 ok；`ADMIN_PASSWORD` 未设置时启动失败并给出明确日志。
- [ ] `/` 画廊：卡片布局在桌面/移动端正常，深浅色模式均美观；空状态正确。
- [ ] 上传 `.html` 后卡片出现，点击进入 `/projects/{slug}/` 正常渲染。
- [ ] 上传含中文文件名、含顶层包装目录、含 `__MACOSX` 的 ZIP：解压正确、入口定位正确。
- [ ] 恶意 ZIP（`../` 路径、符号链接、超量条目、超量解压）被拒绝且无文件逃逸到作品目录之外。
- [ ] 无 `index.html` 的 ZIP 返回明确错误，临时文件与半成品目录被清理。
- [ ] 添加外链：OG 标题/描述/封面自动填充；OG 抓取失败仍能创建作品。
- [ ] `curl -I http://host/projects/{slug}/` 可见 CSP sandbox 头（`PROJECTS_SANDBOX=true` 时）。
- [ ] 上传一个尝试 `document.cookie` 与 `fetch('/api/admin/projects')` 的测试页：均无法读到会话/调用 API。
- [ ] Pin / 上移 / 下移 / 显隐 / 删除 / 改封面均生效；未经登录访问 `/admin` 与 `/api/admin/*` 被拒。
- [ ] 登录失败 5 次触发限流；CSRF 头缺失的写请求被拒。
- [ ] 重启容器后数据完整（DB、作品文件、封面、会话密钥）。
- [ ] 修改 `ADMIN_PASSWORD` 后重启，旧密码失效、新密码可登录。

---

## 13. 未来可扩展点（明确不在 v1）

| 方向 | 思路 |
|------|------|
| 子域隔离 | `/projects/` 迁至 `p.example.com`，关闭 `PROJECTS_SANDBOX`，恢复作品内 `fetch` 能力 |
| 标签与搜索 | projects 增加 tags 表 + 画廊筛选条；SQLite FTS5 做全文搜索 |
| 浏览量 | 轻量计数（IP+UA 去重，写 SQLite），管理台展示 |
| 自动截图封面 | 无头浏览器对 html/zip 作品截图生成封面（镜像变大，需单独评估） |
| 对象存储 | 抽象 storage 接口，支持 S3 兼容后端 |
| 多用户 | 引入用户表与权限，画廊按用户分区（架构改动大，需重新评估隔离模型） |
| 作品版本 | 每次上传保留版本，支持回滚 |
| 密码轮换 | 管理台内修改密码，写入 DB 覆盖 env 同步（需明确优先级规则） |
