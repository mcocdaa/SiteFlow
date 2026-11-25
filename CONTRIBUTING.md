# 贡献指南 (Contributing Guide)

感谢你关注并愿意为 SiteFlow 贡献力量！本项目是 **\*Flow 生态** 的一部分，坚持轻量、安全、零构建、本地优先与 Agent 原生理念。

## 提交前准备

1. **查阅设计与规范**：在开始编码前，请阅读 [AGENTS.md](AGENTS.md)、[DESIGN.md](DESIGN.md) 与 [docs/PLUGIN_DESIGN.md](docs/PLUGIN_DESIGN.md)，了解安全红线与架构契约。
2. **先提 Issue 讨论**：重大架构改动、新增内置应用或调整安全策略前，请先创建 Issue 对齐方案。
3. **区分核心仓库与插件仓库**：
   - 涉及核心平台能力、安全防线、页面契约或内置应用 → 提交到本仓库（`SiteFlow`）。
   - 涉及主题包、页面装饰小部件、徽章、图标替换等纯声明式扩展 → 优先贡献到官方插件包仓库 [`mcocdaa/siteflow-plugins`](https://github.com/mcocdaa/siteflow-plugins)。

## 技术栈与本地环境

SiteFlow 采用 **Python 3.12+ 后端** 与 **零构建原生前端**（无 Webpack/Vite/TypeScript、无外部 CDN）：

- **Python（后端与测试）**：使用 `uv` 管理依赖，代码需满足 Python 3.12 语法、110 列宽，严格通过 `pytest`、`ruff check`、`ruff format --check` 与 `mypy app tests`。
- **原生 JavaScript / CSS / Jinja2（前端）**：所有 `app/static/js/*.js` 直接由浏览器运行，提交前须通过 `node --check` 语法检查，并保持 `app/static/js/i18n.js` 中 `zh` 与 `en` 词典键 100% 对齐；界面图标统一使用纯单色 SVG，禁止使用卡通 Emoji。
- **代码约定**：源码不写冗余注释；严禁提交任何真实 Secret、API Key、`.env` 或本地 `data/` 数据。

```bash
# 1. 安装开发依赖（以 uv.lock 为准）
uv sync --frozen --extra dev

# 2. 本地启动服务
ADMIN_PASSWORD=dev DATA_DIR=./data COOKIE_SECURE=false \
  uv run uvicorn app.main:app --reload --port 8000

# 3. 提交前执行一键全量质量门禁（与 CI 一致）
./scripts/check.sh
```

`./scripts/check.sh` 会自动串联运行：
- `uv run --frozen pytest -q`
- `uv run --frozen ruff check .` 与 `uv run --frozen ruff format --check .`
- `uv run --frozen mypy app tests`
- 全部 `app/static/js/*.js` 的 `node --check` 语法校验
- 仓库一致性与 `i18n.js` 中英键对齐校验

## Git 分支、提交与 PR 合并规范

### 1. 分支与保护规则

- `main` 为受保护主干分支：**禁止直接向 `main` 提交或 force-push**，所有改动必须通过特性分支与 Pull Request 合入。
- 分支命名遵循清晰前缀：
  - `feat/<short-topic>`：新功能或新应用/扩展能力
  - `fix/<short-topic>`：缺陷修复或安全加固
  - `docs/<short-topic>`：文档、README 或 Changelog 更新
  - `refactor/<short-topic>`：不改变外部行为的结构重构
  - `chore/<short-topic>`：CI/CD、依赖或工程脚本维护

```bash
git checkout main && git pull --ff-only
git checkout -b feat/your-feature-name
```

### 2. Conventional Commits 约定

提交信息与 PR 标题遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

- `feat:` / `feat(scope):` 新增功能（如 `feat(admin): add cascade confirmation modal`）
- `fix:` / `fix(scope):` 修复 Bug 或安全隐患
- `docs:` 文档与变更日志更新
- `refactor:` 代码重构
- `test:` 新增或完善测试
- `chore:` / `ci:` 构建、依赖或 CI 工作流维护
- `perf:` 性能优化

### 3. Pull Request 与 CI 合并流程

1. 保持分支基于最新 `main`，按 PR 模板完整填写变更说明、关联 Issue 与验证结果。
2. 本地跑通 `./scripts/check.sh`，并核对 [AGENTS.md](AGENTS.md) 中的全部安全红线。
3. 推送分支并创建 PR，等待 GitHub Actions **CI 流水线全绿**（包含 `Test` 全部静态检查/单测，以及 `Docker` compose 校验 + 镜像构建 + 容器健康与路由冒烟测试）。
4. 评审通过且 CI 全绿后，采用 **Squash and merge** 合入 `main` 并删除远程特性分支，保持提交历史清晰线性与远端分支整洁。

## 配套插件仓库贡献指引（`mcocdaa/siteflow-plugins`）

欢迎为 [https://github.com/mcocdaa/siteflow-plugins](https://github.com/mcocdaa/siteflow-plugins) 贡献纯声明式主题包与功能小部件：

- **包结构**：仓库根目录放置 `siteflow-pack.json` 清单，每个插件位于 `plugins/<plugin_id>/`，包含 `plugin.json` 与静态资产目录 `assets/`（CSS/JS/SVG/字体等，无前端构建步骤）。
- **扩展能力**：可在 `plugin.json` 中声明结构化插槽（`title_deco` / `header` / `aside` / `overlay` / `footer`）、白名单 CSS 主题变量 `tokens`、站内 SVG `icon_overrides` 与表单 `config_schema`。
- **安全与体积约束**：所有 `.svg` 资产不得包含 `<script>`、`on*=` 事件属性、`javascript:`、`foreignObject` 或外部 `http(s)://` 引用；禁止符号链接与路径穿越；单资产文件不得超过 256 KB；所有 `.js` 资产需通过 `node --check`。
- **提交流程**：在 `mcocdaa/siteflow-plugins` 开特性分支提交 PR，待插件仓库 CI 校验（清单合法性、JS 语法、SVG 安全扫描与 ZIP 打包冒烟）全绿后合入。

## 安全漏洞报告

如发现安全隐患，请勿公开提交 Issue，请按 [SECURITY.md](SECURITY.md) 指引通过私密渠道联系维护者。
