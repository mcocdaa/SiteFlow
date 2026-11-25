# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- **PageSurface 统一扩展契约与能力位匹配**（#57, #59, #64）：引入 `app/surface.py`（`PageSurface` / `StaticSurface` / `SurfaceMeta` / `SurfaceItem` / `Capability`），空间、博客、简历与漂流瓶统一实现 `surface()`；插件改为通过 `requires` / `excludes` 能力位声明适用范围，支持 `visitor / plugin / admin` 分层受众视图（保留 `ai` 作为 `plugin` 向后兼容别名）
- **插件配置与启停分层继承**（#60）：新增 `site_settings` 持久化表与 `app/extensions/inheritance.py`，实现 `全站默认 → 父空间 → 子空间/页面` 三层继承与 `inherit / override / disabled` 三态控制，支持按层开关 `cascade` 向下传递、展示生效来源及密钥字段服务端跨层安全继承
- **通用扩展注册表与声明式插件包生态**（#55, #58）：支持博客、空间、简历与漂流瓶通用扩展，内置文章封面、文章背景、空间公告栏、空间背景、空间排布模式、简历样式与看板娘 7 个内置插件；新增「插件订阅源」支持 GitHub 仓库 URL 订阅/同步与离线 ZIP 导入，配套官方仓库 [`mcocdaa/siteflow-plugins`](https://github.com/mcocdaa/siteflow-plugins)
- **结构化插槽、主题变量、图标覆盖与空间排布插件**（#58）：`build_render_bundle` 新增 `header / aside / overlay / footer / title_deco / icons` 结构化插槽、白名单 CSS `tokens` 与站内 SVG `icon_overrides`；新增 `space_layout` 插件，支持 **标准网格 / 瀑布流 / 拍立得 / 可自由拖拽持久化位置的拼贴桌面**（含倾角强度、打乱与归位控制）
- **漂流瓶空间与通用访客提交审核基础设施**（#61）：新增 `app/submissions.py`（`visitor_submissions` 与 `visitor_ip_bans` 表、IP 哈希限频、防混淆禁链检测）与 `bottle` 漂流瓶应用，支持先审后发、投一捞一、蜜罐字段、后台审核队列、IP 封禁/解封与一键清空
- **看板娘 v3 与流式 AI 对话**（#55, #56, #59）：新增可扩展 `MascotCharacterSpec` 角色体系与 7 套纯本地矢量角色（含 MIT 许可的大肥鱼四姿态 SVG：`idle / thinking / speaking / tap`）、自定义头像上传与变量化轮播提示语；集成 DeepSeek（Anthropic 协议）与 OpenAI 兼容流式 AI 对话（支持深度思考折叠、DeepSeek 联网搜索/网页阅读/安全审查），基于 `PageSurface` 通用上下文序列化自动适配博客/空间/简历并提供三层默认提示词与简历隐私隔离
- **富文本 Markdown 与离线 KaTeX 数学公式**（#55）：博客新增 GFM 表格、任务列表、脚注、自动目录锚点、离线内置 KaTeX 0.19.1 数学公式渲染、独立 `BLOG_CSP` 与防闪烁主题初始化脚本
- **实时预览、自动保存与管理端交互组件**（#56, #63）：空间背景与简历样式配置抽屉支持实时预览；简历编辑器支持防抖自动保存；新增 `app/static/js/admin_ui.js`，全后台统一采用 Top Layer (`popover="manual"`) 居中 Toast（支持跨刷新队列、悬停/聚焦暂停与无障碍播报）与防裁切多行 `SiteFlowTooltip`

### 变更

- **全站顶栏纯 SVG 极简按钮与隐私文案泛化**（#64）：画廊、空间、博客、简历、漂流瓶、管理后台、登录与门禁页统一为纯单色 SVG 方形图标按钮搭配悬浮提示；将简历「AI 可见性」升级泛化为「插件隐私控制」并接入 `PageSurface.context("plugin")`
- **管理端插件三态体验与文案精简**（#63）：三态按钮统一为「继承 / 启用 / 关闭」（EN `Inherit / Enable / Off`），「恢复继承」更名为「恢复默认」；上游未启用时禁用「继承」并保留悬浮说明气泡，母空间开启向下继承前弹出二次确认；移除计数角标与常驻长说明段，改由悬浮提示承载，确保 SSR 与 CSR 渲染一致
- **静态资源缓存穿透与编辑体验优化**（#55, #56）：新增基于文件哈希的 `static_url` 不可变缓存、`woff2` MIME 类型注册、空间公告栏排版优化、看板娘空闲气泡渐隐与滚动条安全边距、多行带行号提示语编辑器及完整中英双语键同步

### 安全

- **作品改密门禁凭证立即失效**（#62）：门禁 Token 签入并强校验 `project_password_version`（HMAC `pv` 字段 + `hmac.compare_digest`），作品修改密码后旧解锁 Cookie 在页面访问、看板娘对话与漂流瓶接口立即失效
- **加锁外链强制走门禁跳转**（#62）：非管理员视角在画廊卡片与 `/api/search` 中对加锁外链仅返回 `/projects/{slug}/`，验证通过后返回 `302` 与 `Cache-Control: no-store`，避免提前泄露真实目标 URL
- **插件包、SVG 与 LLM 外呼安全边界**（#55, #60, #61）：外部插件包 GitHub 同步与看板娘 AI 接口强制校验公网 HTTPS 与私网 IP 阻断（SSRF 防护）；自定义头像与插件包 SVG 严格执行安全净化；敏感配置密钥仅服务端存储与合并，绝不向前端泄明文；漂流瓶提交接口强制同源校验、先审后发与防混淆禁链

### 修复

- **无头重部署保留项目可见性**（#62）：`PUT /api/admin/projects/{slug}/deploy` 更新已有项目时省略 `visible` 字段将保留原可见性，不再意外重置为公开（新建项目仍默认可见）
- **简历数据完整性与防静默截断**（#62）：`PATCH` 更新简历时若 `basics` 省略 `image` 字段则保留库中已有头像（显式传 `""` 仍允许清空）；工作摘要与项目描述上限提升至 2000 字、要点上限提升至 500 字，超长或超量时返回 422 明确提示而非静默截断
- **时钟偏移容错与管理页间距修复**（#55, #63）：签名会话与门禁令牌新增 5 秒时钟偏移容错；统一修复管理页列表、面板与插件头部的间距紧贴问题

## [2.3.1] - 2026-11-07

### 修复与优化

- 统一根管理台与空间管理页「添加内容」入口，支持多文件选择、批量拖拽上传与单文件失败重试
- 支持已设置封面的多次更换（带缓存穿透文件名）与一键恢复默认矢量封面
- 重构独立每篇博客文章沉浸式 Markdown 编辑页，新增保存失败行内错误提示与未保存输入保护
- 新增基于 SQLite `daily_visitors` 的持久化日去重 PV/UV 统计，排除管理员会话、预览弹窗与入口重定向干扰
- Docker 构建优化：`Dockerfile` 与 `docker-compose.yml` 支持可配置 `PIP_INDEX_URL` 加速源与超时重试，`deploy/init.sh` 默认镜像标签同步升级至 `v2.3.1`

## [2.2.1] - 2026-09-30

### 修复

- UI/交互细节优化：居中上传拖拽区图标并优化空态布局，移除冗余编辑提示横幅与搜索快捷键角标
- 预览视口交互修复：提升预览顶栏层级避免二维码气泡遮挡工具提示，点击外部或切换视口时自动收起真机调试二维码气泡
- 密码保护交互改进：提供独立清除密码操作，移除占位符中冗余的 `clear` 文案提示

## [2.2.0] - 2026-09-30

### 新增

- 全局命令面板（`Cmd+K` / `Ctrl+K` / `/`）与 `/api/search` 实时检索接口，支持快捷跳转与深浅色主题切换
- 空间个性化主题（自定义强调色、字体族、卡片圆角）与基于 `BASE_DOMAIN` 的子域名直达路由
- 隐私友好的轻量级访问统计（7 日 PV/UV 去重计数与 SVG Sparkline 趋势图）
- 单作品独立密码保护（`/projects/{slug}/unlock`）与路径隔离签名 Cookie
- 多视口响应式安全预览弹窗（桌面/平板/手机/横竖屏切换）与局域网真机调试二维码（`/api/qrcode`）
- 程序化矢量网格默认封面（`/media/placeholder/{slug}.svg`）与静态资源 `ETag` / `304 Not Modified` 缓存协商

### 安全

- ZIP 解压防护升级：新增膨胀率（Expansion Ratio）炸弹检测、Inode 数量上限校验与 Windows GBK 中文文件名兼容解码

## [1.1.0] - 2026-09-20

### 新增

- 应用（Application）：内置 `space` 空间，统一 `/projects/` 路由；核心不含具体插件，静态站点即普通 HTML/ZIP 项目
- 应用注册表 `app/plugins/`（AppPlugin 协议 + 插件模板目录自动加载）：`space` 作为第一个应用注册，管理台「应用」列表由注册表生成
- 管理台：新建按钮由应用列表生成、应用管理页（面包屑/子项/嵌套上传/深度限制）
- 嵌套上限 3 层；叶子类型禁止包含子项；删除级联清理文件；可见性沿祖先继承
- 简历插件（JSON Resume 子集）：单页时间线、打印导出、管理台编辑器
- 博客插件：文章列表/详情，Markdown 安全渲染（markdown-it-py，禁用原始 HTML 与危险链接）
- 统一 `*Flow` 生态治理规范、脚本与文档体系

### 修复

- 已登录访问 `/login` 不再覆盖会话，直接 303 跳转 `/admin`

## [1.0.1] - 2026-09-18

修复版本：依赖与部署工具链更新，无界面行为变化。

### 修复

- 依赖升级：httpx ≥0.28.1、python-multipart ≥0.0.32、sqlalchemy ≥2.0.53、argon2-cffi ≥25.1.0、mypy ≥2.3.1（开发依赖）
- 构建基础镜像升级 `python:3.14-slim`（CI 构建与 healthz 冒烟、本地测试均通过）

### 变更

- `deploy/`：新增无源码镜像部署（`init.sh`/`stop.sh`/`.env.example`），支持 `TAG` / `SITEFLOW_PORT` / `SITEFLOW_NAME`
- `docker-compose.yml` 镜像指向 `ghcr.io/mcocdaa/siteflow`
- Release 工作流同时发布 `v{{version}}` 与 `{{version}}` 镜像 tag
- 新增 Dependabot 配置（docker / pip）

## [1.0.0] - 2026-09-18

首个正式版本。

### 新增

- 三类作品：单 HTML、ZIP 静态站点（站内全屏查看）、外链（卡片新标签跳转）
- 画廊页：卡片网格、置顶、空状态、深浅色自适应、无构建无 CDN
- 管理台：拖拽上传、外链 OG 自动填充、封面、Pin、上移/下移、显隐、删除
- Docker 单容器部署：健康检查、非 root（uid 1000）运行、`/data` 数据卷
- `scripts/start.sh`（docker/local）、`stop.sh`、`check.sh`
- CI（pytest + ruff + mypy + JS 语法 + Docker 冒烟）与 Release 工作流（GHCR 发布）

### 安全

- 作品统一 `CSP: sandbox` 不透明源隔离，无法触达主站会话与 `/api/admin/*`
- ZIP 解压拒绝 `..`、绝对路径、符号链接、加密条目、超量条目与超限解压
- 平台外呼（OG/封面图）私网校验 + 超时 + 大小与重定向上限（SSRF 防护）
- 管理写操作三重校验：登录会话 + 同源（Origin/Host）+ CSRF
- 登录限流（5 次/15 分钟），修改 `ADMIN_PASSWORD` 后旧会话立即失效
- `PROJECTS_SANDBOX=false` 时拒绝启动

### 测试

- 23 项 pytest：冒烟、流程（上传/外链/排序/封面/入口）、安全（zip-slip、符号链接、
  解压限制、SSRF、CSRF、限流、改密失效、路径穿越）
