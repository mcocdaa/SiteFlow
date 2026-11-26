# AGENTS.md

SiteFlow：Docker 化个人作品画廊与可扩展页面平台（FastAPI + SQLite + Jinja2，零前端构建）。
产品与安全设计见 `DESIGN.md`、`DESIGN-v2.md`，插件契约见 `docs/PLUGIN_DESIGN.md`，Agent API 见 `docs/API_V1.md`，用户文档见 `README.md` / `README_CN.md`。界面文案与测试断言使用中文（前端需同步维护 `app/static/js/i18n.js` 中英双语键）。

## 命令

```bash
# 首次准备（uv 锁文件为准）
uv sync --frozen --extra dev

# 提交前必须全绿（一键跑全套门禁：pytest + ruff check/format + mypy + 全部 JS 语法 + 仓库/i18n 校验）
./scripts/check.sh

# 也可分项执行
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy app tests
for f in app/static/js/*.js; do node --check "$f"; done

# 本地运行
ADMIN_PASSWORD=dev DATA_DIR=./data COOKIE_SECURE=false \
  uv run uvicorn app.main:app --reload --port 8000
```

## 结构

| 路径 | 职责 |
|------|------|
| `app/main.py` | `create_app()` 工厂、`/api/v1` 错误与参数校验处理器、全局安全响应头中间件、静态 MIME 注册 |
| `app/routes.py` | 聚合 router（views + admin + api_v1 + mascot_chat + bottle API） |
| `app/views.py` | 画廊、作品文件、门禁解锁、加锁外链跳转、封面/插件媒体、搜索、登录/登出、`/healthz` |
| `app/admin.py` | `/admin` 页面与 `/api/admin/*`（项目/部署/全站及项目扩展/插件包/访客审核/API 令牌）写接口 |
| `app/api_v1.py` | 面向通用 Agent 与自动化的 `/api/v1/*` REST 路由（`whoami`、鉴权 `openapi.json`、项目树、博客文章/插图、结构化内容、静态部署、扩展、审核与令牌管理） |
| `app/project_service.py` | 项目、博客文章/媒体、结构化内容、封面、静态部署与扩展/审核的共享服务层（抛 `ServiceError`） |
| `app/tokens.py` | 数据库细粒度可吊销 API 令牌（`sft_` 前缀、SHA-256 哈希存储、`AuthPrincipal`、Scope 与 `allowed_slugs` 校验） |
| `app/deps.py` | `DbSession` / `AdminConfig` / `ApiAuth` 依赖、`ServiceError`、`require_scope` / `require_project_access`、`api_error` |
| `app/auth.py` | 会话签名、CSRF、登录/门禁限流、管理员 `password_version` 与单作品 `project_password_version` |
| `app/store.py` | SQLite WAL 会话工厂、迁移（含 `site_settings`/`daily_visitors`/`visitor_submissions`/`api_tokens`）与查询排序 |
| `app/surface.py` | `PageSurface` 契约（`SurfaceMeta`/`SurfaceItem`/`StaticSurface`/`Audience`/`Capability`） |
| `app/extensions/` | 通用扩展体系：`base.py` 协议与校验、`inheritance.py` 三层继承、`packs.py` 声明式插件包、`registry.py` 调度、`mascot.py`/`mascot_chat.py` 看板娘与 AI 对话、`space_layout.py` 等内置扩展 |
| `app/submissions.py` | 通用访客提交审核存储（`visitor_submissions`/`visitor_ip_bans`）、IP 哈希限频、防混淆禁链 |
| `app/plugins/` | 应用注册表（`space`/`resume`/`blog`/`bottle`）+ `base.py` 协议；插件自带模板目录 |
| `app/plugins/bottle/` | 漂流瓶空间应用（`plugin.py`、`api.py` 公开投递/捞取端点与模板） |
| `app/og.py` | OG 元数据、封面图与插件包归档抓取（私网校验、超时、大小/重定向上限） |
| `app/uploads.py` | ZIP 安全解压（含膨胀率炸弹检测）、SVG 净化、封面与扩展媒体清理 |
| `app/stats.py` | UTC 日去重 PV/UV 统计与 SVG Sparkline |
| `app/templating.py` | Jinja2 环境与基于内容哈希的 `static_url` |
| `app/models.py` | `Project` SQLAlchemy 模型 |
| `app/static/js/admin_ui.js` | 管理端通用 Top Layer (`popover="manual"`) Toast 与防裁切多行 `SiteFlowTooltip` |
| `app/static/` `app/templates/` | 零构建原生 CSS/JS（含 `i18n.js` 双语词典与离线 KaTeX）及页面模板 |
| `tests/` | 冒烟/流程/安全/应用/PageSurface/分层继承/漂流瓶回归测试；`conftest.py` 每个用例重建数据目录 |

## 约定

- Python 3.12 目标语法，行宽 110，依赖以 `pyproject.toml`、`uv.lock` 与 `requirements.txt` 同步维护。
- 路由默认同步 `def`（FastAPI 线程池）；只有需要 `await` 的上传或流式接口用 `async def`，禁止在 async 路由里做阻塞 IO。
- 数据库会话一律通过 `DbSession` 依赖注入，不要在路由里手写 `store.init(config)()`。
- 平台外呼（OG/封面/插件包归档）必须走 `app/og.py`，LLM 外呼沿用 `mascot_chat.py` 的公网 HTTPS 与私网 IP 校验。
- `app/surface.py`、`app/extensions/base.py`、`app/extensions/inheritance.py` 等 base 层禁止硬编码分支具体插件 ID 或页面类型。
- 新增或修改前端文案时必须保持 `app/static/js/i18n.js` 中 `zh` 与 `en` 键 100% 对齐；界面统一使用纯单色 SVG 图标，禁用卡通 Emoji。
- 代码中不写注释；模板不引 CDN，不引入前端构建步骤。

## 安全红线（改动必须保持）

1. `/projects/*` 静态文件（html/zip）响应带 `CSP: sandbox ...`（`views.SANDBOX_CSP`）；`space`/`resume`/`blog`/`bottle` 由我们的模板渲染（`blog`/`bottle` 带独立严格 CSP），所有用户内容必须保持 Jinja 自动转义。
2. ZIP 解压（作品上传与离线插件包）拒绝 `..`、绝对路径、符号链接、加密条目、超量条目、超限解压与高膨胀率炸弹；自定义头像与插件包 SVG 必须经 `sanitize_svg` 净化。
3. 管理写操作必须经过 `admin_api`：登录（或 Bearer API Token）+ 同源 + CSRF 三重校验；应用嵌套必须服务端校验父级为 `space` 且深度 < 3，叶子类型禁止包含子项。
4. 修改 `ADMIN_PASSWORD` 后旧管理会话立即失效（`password_version`）；**修改单作品访问密码后旧门禁凭证立即失效**（`project_password_version` HMAC `pv` 字段强校验，views、mascot chat 与 bottle API 全链路一致校验）。
5. **加锁外链必须走门禁跳转**：非管理员视角在画廊卡片与 `/api/search` 中仅暴露 `/projects/{slug}/`，不得提前泄露 `project.url`；门禁校验通过后返回 `302` 且带 `Cache-Control: no-store`。
6. **访客提交端点安全红线**（如漂流瓶 `/api/projects/{slug}/bottle/*`）：独立公开 API 必须执行同源校验（`require_same_origin`）、默认先审后发（`pending`）、服务端防混淆禁链（`submissions.contains_link`）、按 `ip_hash` 限频与封禁检查，并校验项目可见性与密码门禁。
7. `PROJECTS_SANDBOX=false` 时 `Config.load()` 拒绝启动，不要移除该限制；插件密钥（`secret_fields`）仅服务端存储与跨层合并，禁止明文下发前端。
8. **API 令牌与 `/api/v1/*` 安全红线**：DB 令牌（`api_tokens`）仅存 SHA-256 哈希与前缀，明文只在创建时返回一次；低权或限定项目作用域的 DB 令牌一律拦截 `/api/admin/*`（403）；`/api/v1/*` 强制携带 `Cache-Control: no-store`，`/api/v1/openapi.json` 必须鉴权读取（保持根 `/docs` `/redoc` `/openapi.json` 关闭）；受限令牌新建、部署或迁移项目时必须执行作用域逃逸校验，修改项目密码须额外具备 `admin` 权限。
