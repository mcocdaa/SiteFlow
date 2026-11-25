# SiteFlow 插件体系设计（PageSurface 契约）

> 状态：已实施（步骤 1–8 与首批消费者均已合入 `main`，对应 PR #55–#64）。本文记录已落地的 `PageSurface` 契约、分层继承、访客提交基础设施与安全不变量。

## 0. 术语

| 术语 | 实际代码位置 | 含义 |
|------|--------------|------|
| 页面类型（Page Type） | `app/plugins/`（`AppPlugin`：`space` / `blog` / `resume` / `bottle`） | 拥有数据、声明能力位并负责渲染一类页面 |
| 扩展插件（Extension / Plugin） | `app/extensions/`（`mascot`、`space_background`、`space_banner`、`space_layout`、`post_cover`、`post_background`、`resume_style` 与外部声明式 pack） | 挂在页面上的增强能力，通过能力位与插槽接入 |
| base 基础设施 | `app/surface.py`、`app/plugins/base.py`、`app/extensions/base.py`、`app/extensions/inheritance.py`、`app/extensions/registry.py`、`app/submissions.py` 与骨架模板 | 双方共同依赖的契约、分层继承调度与通用访客提交存储 |

## 1. 设计原则

1. **单向依赖**：扩展插件依赖 base，页面类型依赖 base；base 不 import、不分支任何具体插件或页面类型。
2. **base 只为通用接入演进**：新增通用插槽、通用能力位、通用继承规则与通用审核存储可以；禁止在 base 中写 `if ext.id == "mascot"` 等特判。
3. **页面类型与插件互不认识**：二者唯一的语义交汇点是 `PageSurface`。插件不直接解析 `project.content` 私有结构，页面不感知具体启用了哪些插件。
4. **隐私由数据提供方负责**：页面类型在 `surface()` 中按 `audience` 自行过滤数据；插件消费 `context("plugin")`（或兼容别名 `context("ai")`）拿到什么即可使用什么，无需也不应在插件侧重复做字段脱敏。
5. **适用性靠能力位声明**：插件通过 `requires` / `excludes` 声明所需页面能力位（旧插件可由 `targets` 自动推导），新增页面类型时无需修改既有插件。

## 2. PageSurface 契约（已落地）

### 2.1 组成

| 字段 / 能力 | 说明 |
|-------------|------|
| `meta` | `SurfaceMeta(type, slug, title, description, url, parent_chain)`，任何插件可安全读取 |
| `context(audience)` | 页面语义数据。`visitor`：公开可见内容；`plugin`：提供给扩展插件与外部服务读取的过滤后内容（比 `visitor` 更严，如简历默认隐藏邮箱/电话/所在地）；`ai`：`plugin` 的向后兼容别名（`StaticSurface.context()` 中 `plugin` 与 `ai` 互作回退，再回退 `visitor`）；`admin`：完整管理数据 |
| `slots` | 结构化注入插槽：`header` / `aside` / `overlay` / `footer` / `title_deco` / `icons`（同时向后兼容 `start` / `main_start` / `end`） |
| `tokens` | 白名单 CSS 设计变量（`--accent`、`--accent-soft`、`--bg`、`--surface`、`--radius-card`、`--font-family` 等）与 `icon_overrides` 站内 SVG 图标覆盖；主题插件写、页面模板读 |
| `items` | 页面的可列举条目（`SurfaceItem`：空间子项、博客文章、简历段落），支持 `layout` 类插件接管排布 |
| `capabilities` | 布尔能力位集合：`has_content`、`has_children`、`has_items`、`has_posts`、`accepts_visitor_input`、`is_personal_profile`、`supports_layout` |

### 2.2 核心契约实现（`app/surface.py` 与 `app/extensions/base.py`）

```python
Audience = Literal["visitor", "plugin", "ai", "admin"]
SlotName = Literal["header", "aside", "overlay", "footer", "title_deco", "icons"]
Capability = Literal[
    "has_content",
    "has_children",
    "has_items",
    "has_posts",
    "accepts_visitor_input",
    "is_personal_profile",
    "supports_layout",
]


@dataclass(frozen=True)
class SurfaceMeta:
    type: str
    slug: str
    title: str
    description: str
    url: str
    parent_chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceItem:
    key: str
    title: str
    url: str
    summary: str = ""
    cover: str = ""
    kind: str = ""
    tags: tuple[str, ...] = ()


class PageSurface(Protocol):
    @property
    def meta(self) -> SurfaceMeta: ...
    @property
    def capabilities(self) -> frozenset[Capability]: ...
    def context(self, audience: Audience) -> Mapping[str, Any]: ...
    def items(self, audience: Audience) -> Sequence[SurfaceItem]: ...
    def tokens(self) -> Mapping[str, str]: ...
```

渲染调度由 `app/extensions/registry.py` 中的 `build_render_bundle()` 统一完成：`resolve_project_extensions()`（三层继承 + 能力位匹配）→ 收集 `static_css` / `static_js` / `body_classes` / `tokens`（经 `sanitize_theme_tokens` 白名单校验）/ `icon_overrides`（经 `sanitize_icon_overrides` 路径校验）/ `layout_mode` / 结构化 `slots` 与兼容旧槽位 → 交付统一模板骨架渲染。

### 2.3 四类内置页面的实现

| 页面类型 | `capabilities` | `context("visitor")` | `context("plugin" / "ai")` | `items` |
|----------|----------------|----------------------|----------------------------|---------|
| `space`（`app/plugins/space.py`） | `has_children, has_items, supports_layout` | 标题、简介、可见子项标题列表 | 同 `visitor`（仅含可见子项，不泄隐藏项） | `store.visible_projects()` 的子项 |
| `blog`（`app/plugins/blog/plugin.py`） | `has_content, has_posts, has_items, supports_layout` | 博客标题/简介；文章页附当前文章 | 标题/日期/标签/摘要/正文节选（截断至 `MAX_AI_BODY = 1500` 字） | 文章列表 |
| `resume`（`app/plugins/resume/plugin.py`） | `has_content, is_personal_profile, has_items` | 公开展示的简历字段 | 按「插件隐私控制（`ai_visibility`）」过滤：默认隐藏 `email`/`phone` 与 `location`，支持按板块开关；`plugin` 与 `ai` 指向同一过滤上下文 | 工作/教育/项目/技能段落 |
| `bottle`（`app/plugins/bottle/plugin.py`） | `accepts_visitor_input, has_items` | 标题、简介、海滩欢迎语、已过审瓶数与规则配置 | 同 `visitor`（不泄露待审队列、IP 哈希或访客私密数据） | —（访客提交由 `visitor_submissions` 独立管理） |

`app/extensions/mascot_chat.py` 不再按 `project.type` 分支读取私有 JSON，而是直接调用 `plugin.surface()` 并通用序列化 `surface.context("plugin")`（兼容 `"ai"`），使博客、空间与简历天然共享看板娘对话能力且严格遵守各自隐私边界。

## 3. 配置与启停：三层分层继承（已落地）

### 3.1 层级与存储

```text
全站默认 (site_settings 表 key="site_extensions")
  →  父空间 (space, 嵌套深度 < 3, 需 cascade=true 向下传递)
    →  当前页面 (space / blog / resume / bottle)
```

每层对每个扩展插件的状态遵循三态模型（`app/extensions/inheritance.py`）：

| 存储 `mode` | 管理台标签（中 / EN） | 含义 |
|-------------|------------------------|------|
| `inherit`（缺省 / 键缺失） | 继承 / Inherit | 沿用上游层的启停状态与合并配置 |
| `override` | 启用 / Enable | 在本层启用，并以本层稀疏 `config` 浅合并覆盖上游配置 |
| `disabled` | 关闭 / Off | 在本层（及若 `cascade=true` 且未再 `override` 的下层）关闭 |

存储格式（同时向下兼容历史 `{installed, enabled, config}` 格式）：

```json
"extensions": {
  "siteflow-plugins.dafeiyu_theme": {
    "mode": "override",
    "cascade": true,
    "config": {}
  }
}
```

- **全站默认层**：存储在 SQLite `site_settings` 键值表的 `site_extensions` 键中（`store.get_site_setting` / `store.set_site_setting`），默认 `cascade=true`；管理接口为 `GET/PUT/DELETE /api/admin/site/extensions`。
- **空间与页面层**：存储在 `project.content["extensions"]` 中；旧格式自动映射为 `enabled=true → override`、`enabled=false → disabled`、`installed=false → inherit`。

### 3.2 解析规则与管理端交互

1. **自顶向下折叠**：沿 `site → store.ancestors(db, project) → project` 折叠计算 `ResolvedExtension`（包含 `effective_enabled`、`effective_config`、`source`、`source_title`、`inherited_enabled`、`local_mode`、`cascade`）。
2. **能力位过滤**：校验 `ext.matches_capabilities(surface.capabilities)`，仅展示并生效与当前页面能力位匹配的插件。
3. **密钥安全继承**：`secret_fields`（如看板娘 `api_key`）仅持久化在配置它的层，跨层合并在服务端完成；接口只返回 `secrets_set`、`local_secrets_set` 与 `secret_inherited` 布尔标记，前端永不接收明文密钥。
4. **管理端三态与级联保护**：
   - 当全站及所有父空间均未启用某插件时，管理台自动禁用「继承」按钮（保留悬浮说明气泡）并默认视觉选中「关闭」；
   - 点击「恢复默认」可一键切回 `inherit` 并清理本层覆盖；
   - 在父空间勾选「向下级子项继承（`cascade`）」前触发二次确认弹窗，取消立即还原不发请求；
   - 卡片直接标明当前生效来源（全站默认 / 某父空间 / 当前页）。

## 4. 实施里程碑（步骤 1–8 全部合入 `main`）

| 步骤 | 目标 | 落地 PR 与核心模块 |
|------|------|--------------------|
| 1 | 引入 `PageSurface` 契约，空间/博客/简历实现 `surface()` | PR #57：`app/surface.py`、`app/plugins/{space,blog,resume}` |
| 2 | AI 对话上下文统一改走 `PageSurface` 序列化与隐私过滤 | PR #59, #64：`app/extensions/mascot_chat.py`、`ResumeApp.surface()`（`plugin` / `ai` 受众） |
| 3 | 能力位（`requires`/`excludes`）替代硬编码 `targets` | PR #59：`app/extensions/base.py`、`app/extensions/registry.py`（含 `infer_capabilities_from_targets` 兼容） |
| 4 | 结构化插槽、`tokens` 白名单与 `icon_overrides` | PR #58：`app/extensions/base.py`、`app/extensions/packs.py`、`app/extensions/registry.py` |
| 5 | 统一扩展渲染聚合通道（兼容声明式外部 pack 与内置扩展） | PR #55, #58：`build_render_bundle()` 统一汇总结构化插槽、旧槽位、变量与脚本资产 |
| 6 | 三层分层继承（全站默认 → 父空间 → 当前页）与密钥安全继承 | PR #60, #63：`app/extensions/inheritance.py`、`site_settings` 表、三态 UI 与级联确认 |
| 7 | `items` 暴露与空间排布布局插件 | PR #58：`app/extensions/space_layout.py`、`app/static/js/ext_space_layout.js` |
| 8 | 通用访客提交审核与限频基础设施 + 漂流瓶应用 | PR #61：`app/submissions.py`、`visitor_submissions` / `visitor_ip_bans` 表、`app/plugins/bottle/` |

## 5. 首批消费者（均已上线）

| 消费者 | 类型 | 能力要求（`requires`） | 落地位置与要点 |
|--------|------|------------------------|----------------|
| 大肥鱼主题包（`dafeiyu_theme`） | 声明式主题包 | 无（全站通用） | 托管于 [`mcocdaa/siteflow-plugins`](https://github.com/mcocdaa/siteflow-plugins)；仅声明白名单 `tokens`、`icon_overrides` 与 `title_deco` 装饰，可在全站默认层一键开启、子空间按需关闭 |
| 空间排布模式（`space_layout`） | 内置布局插件 | `has_items, supports_layout`（排除 `has_posts`） | `app/extensions/space_layout.py`；支持标准网格 / 瀑布流 / 拍立得 / 自由拖拽拼贴桌面（`localStorage` 持久化位置、倾角与打乱/归位） |
| 简历看板娘（`mascot`） | 内置交互插件 | 无（全页面通用） | `app/extensions/mascot.py` + `mascot_chat.py`；消费 `surface.context("plugin")`，提供简历专用默认提示词，联系方式与地区受简历「插件隐私控制」默认隐藏 |
| 漂流瓶空间（`bottle`） | 内置交互应用 | 页面声明 `accepts_visitor_input, has_items` | `app/plugins/bottle/` + `app/submissions.py`；先审后发、投一捞一（签名 Cookie 积分且排除本人）、IP 哈希限频、防混淆禁链、蜜罐字段、后台审核/封禁/一键清空 |

## 6. 持续保持的安全不变量

- 严格遵守 [AGENTS.md](../AGENTS.md) 全部安全红线：静态作品持续使用 `CSP: sandbox`，模板输出经 Jinja 自动转义，`Markup` 仅来源于受控插件模板。
- 声明式插件包仅加载白名单 CSS 变量、受限本地 SVG 图标与静态资产，不执行任何服务端远程代码；SVG 资产强制执行安全净化。
- 外部平台外呼统一走 `app/og.py`，LLM 外呼沿用 `mascot_chat.py` 的公网 HTTPS 与私网 IP 校验。
- 访客公开提交路由独立于 `admin_api`，仍强制同源校验、可见性/门禁校验（含 `project_password_version`）、防混淆禁链与 IP 限频。
- base 层不得出现具体插件 ID 或页面类型字符串硬编码分支。
