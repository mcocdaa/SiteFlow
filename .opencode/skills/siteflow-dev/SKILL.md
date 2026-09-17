---
name: siteflow-dev
description: Use when changing the SiteFlow repo (FastAPI gallery app in this project) - routes, auth, uploads, templates, tests, Docker, or when asked to run SiteFlow verification commands. Covers module layout, test commands, and security invariants that must not regress.
---

# SiteFlow 开发流程

## 修改前

- 先读 `DESIGN.md` 对应章节，保持已批准行为：单管理员、三类作品（html/zip/link）、pin + 手动排序、无标签/搜索。
- 定位入口：页面在 `app/views.py`，管理写接口在 `app/admin.py`，数据访问在 `app/store.py`，公共依赖在 `app/deps.py`。

## 验证命令（必须全绿）

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app tests
node --check app/static/js/admin.js
```

需要真实 HTTP 验证时（数据目录用临时目录，避免污染仓库）：

```bash
ADMIN_PASSWORD=dev DATA_DIR=$(mktemp -d) COOKIE_SECURE=false \
  .venv/bin/uvicorn app.main:app --port 8000
```

## 安全清单（改完逐条自查）

- `/projects/*` 响应是否保留 `CSP: sandbox ...`？
- 新增外呼是否经过 `app/og.py`（`_safe_host` + 超时 + 大小/重定向上限）？
- 新增写接口是否使用 `AdminConfig` 依赖（登录 + 同源 + CSRF）？
- 文件读写路径是否用 `is_relative_to` 做了目录逃逸校验？
- 改密失效、限流、CSRF 的用例（`tests/test_security.py`）是否仍通过？

## 测试习惯

- 新行为加测试：业务流程放 `tests/test_flow.py`，安全边界放 `tests/test_security.py`。
- 测试数据目录由 `tests/conftest.py` 每用例重建，不要在用例里写死固定路径。
- 界面断言用中文文案；不要为测试改产品行为。
