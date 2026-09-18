# AGENTS.md

SiteFlow：Docker 化个人作品画廊（FastAPI + SQLite + Jinja2，无前端构建）。
产品与安全设计见 `DESIGN.md`，用户文档见 `README.md`。界面文案与测试断言使用中文。

## 命令

```bash
# 首次准备
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# 提交前必须全绿（或直接 ./scripts/check.sh）
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app tests
node --check app/static/js/admin.js

# 本地运行
ADMIN_PASSWORD=dev DATA_DIR=./data COOKIE_SECURE=false \
  .venv/bin/uvicorn app.main:app --reload --port 8000
```

## 结构

| 路径 | 职责 |
|------|------|
| `app/main.py` | `create_app()` 工厂、全局安全响应头中间件 |
| `app/routes.py` | 聚合 router（views + admin） |
| `app/views.py` | 画廊、作品文件、封面、登录/登出、`/healthz` |
| `app/admin.py` | `/admin` 页面与 `/api/admin/*` 写接口 |
| `app/deps.py` | `DbSession` / `AdminConfig` 依赖、`api_error` |
| `app/auth.py` | 会话签名、CSRF、登录限流、密码校验与失效 |
| `app/store.py` | SQLite 会话工厂与全部查询/排序 |
| `app/plugins/` | 应用注册表（space 为注册的第一个应用）+ base 协议；插件自带模板目录 |
| `app/og.py` | OG 元数据与封面图抓取（私网校验、大小/重定向上限） |
| `app/uploads.py` | ZIP 安全解压、封面处理、文件清理 |
| `app/templating.py` | Jinja2 环境 |
| `app/models.py` | `Project` 模型 |
| `app/static/` `app/templates/` | 手写 CSS/JS 与页面模板 |
| `tests/` | 冒烟/流程/安全/应用测试；`conftest.py` 每个用例重建数据目录 |

## 约定

- Python 3.12 目标语法，行宽 110，只用 `requirements*.txt` 中的依赖。
- 路由默认同步 `def`（FastAPI 线程池）；只有需要 `await` 的上传接口用 `async def`，禁止在 async 路由里做阻塞 IO。
- 数据库会话一律通过 `DbSession` 依赖注入，不要在路由里手写 `store.init(config)()`。
- 平台外呼（OG/封面）必须走 `app/og.py`，保留私网校验、超时、大小与重定向限制。
- 不写注释；模板不引 CDN，不引入构建步骤。

## 安全红线（改动必须保持）

1. `/projects/*` 静态文件（html/zip）响应带 `CSP: sandbox ...`（`views.SANDBOX_CSP`）；
   `space`/`resume` 由我们的模板渲染，所有用户内容必须保持 Jinja 转义。
2. ZIP 解压拒绝 `..`、绝对路径、符号链接、加密条目、超量条目与超限解压。
3. 管理写操作必须经过 `admin_api`：登录 + 同源 + CSRF 三重校验；
   应用嵌套必须服务端校验父级为 space 且深度 < 3，叶子类型禁止包含子项。
4. 修改 `ADMIN_PASSWORD` 后旧会话立即失效（`password_version`）。
5. `PROJECTS_SANDBOX=false` 时 `Config.load()` 拒绝启动，不要移除该限制。
