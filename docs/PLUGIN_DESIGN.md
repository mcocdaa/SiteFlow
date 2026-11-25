# SiteFlow 插件体系设计（PageSurface 契约）

> 状态：设计草案，未实施。本文只描述目标与迁移路线，不改变现有行为与 `AGENTS.md` 安全红线。

## 0. 术语

| 术语 | 现有代码 | 含义 |
|------|----------|------|
| 页面类型（Page Type） | `app/plugins/`（`AppPlugin`：space/blog/resume） | 拥有数据、负责渲染一类页面 |
| 插件（Plugin） | `app/extensions/`（`Extension`：mascot、space_background、space_banner、post_cover、post_background、resume_style、外部 pack） | 挂在页面上的增强能力 |
| base | `app/plugins/base.py`、`app/extensions/base.py`、`registry.py`、模板骨架 | 双方共同依赖的契约与调度 |

## 1. 设计出发点

1. **单向依赖**：插件依赖 base，页面类型依赖 base；base 不 import、不分支任何具体插件或页面类型。
2. **base 可以改，但只为“所有插件更好接入”而改**：新增通用槽位、通用能力位、通用继承规则可以；为某一个插件在 base 里写 `if ext.id == "mascot"` 不可以。
3. **页面类型与插件互不认识**：二者唯一的交汇点是 `PageSurface`。插件不读 `project.content` 的私有结构，页面不知道有哪些插件。
4. **隐私由数据提供方负责**：页面类型按 `audience` 自行过滤后才把数据放进 surface；插件拿到什么就可以用什么（含发给 AI），无需也不应再做字段级脱敏。
5. **适用性靠能力声明**：插件不写 `targets=("blog","space")`，而声明 `requires={"has_content"}`；新增页面类型时无需修改任何插件。

## 2. PageSurface 契约

### 2.1 组成

| 字段 | 说明 |
|------|------|
| `meta` | `type / slug / title / description / url / lang / cover / parent_chain`，任何插件可安全读取 |
| `context(audience)` | 页面语义数据。`visitor`：公开可见内容；`plugin`：通过统一接口提供给扩展插件与外部服务读取的过滤后内容（比 visitor 更严，如简历默认去掉电话/邮箱/所在地）；`ai`：`plugin` 的向后兼容别名（`StaticSurface.context()` 中 `plugin` 与 `ai` 互作回退，再回退 `visitor`）；`admin`：完整数据 |
| `slots` | 插件可注入的位置：`header` / `aside` / `overlay` / `footer` / `title_deco` / `icons`（兼容旧 `start/main_start/end`） |
| `tokens` | CSS 变量（`--accent`、`--radius-card`、字体…）与图标集；主题插件写、页面模板读 |
| `items` | 页面的可列举条目（空间子项、博客文章、简历段落），交给布局插件排布 |
| `capabilities` | 布尔/枚举能力位，插件据此声明适用性 |

能力位初始集合：`has_content`、`has_children`、`has_items`、`has_posts`、`accepts_visitor_input`、`is_personal_profile`、`supports_layout`。新增能力位属于“为所有插件改 base”，允许。

### 2.2 Python Protocol 草案

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
    parent_chain: tuple[str, ...]


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
    meta: SurfaceMeta
    capabilities: frozenset[Capability]

    def context(self, audience: Audience) -> Mapping[str, Any]: ...
    def items(self, audience: Audience) -> Sequence[SurfaceItem]: ...
    def tokens(self) -> Mapping[str, str]: ...


class SurfaceProvider(Protocol):
    def surface(self, request: Request, project: Project, db: Session, *, sub: str = "") -> PageSurface: ...


@dataclass
class Contribution:
    slots: dict[SlotName, list[Markup]]
    tokens: dict[str, str]
    css: list[str]
    js: list[str]
    body_classes: list[str]
    layout: str | None = None


class Plugin(Protocol):
    manifest: "PluginManifest"

    def contribute(
        self, surface: PageSurface, config: Mapping[str, Any], *, is_admin: bool
    ) -> Contribution: ...


@dataclass(frozen=True)
class PluginManifest:
    id: str
    version: str
    requires: frozenset[Capability]
    excludes: frozenset[Capability] = frozenset()
    kind: Literal["decor", "theme", "layout", "interactive"] = "decor"
    config_schema: tuple[ConfigField, ...] = ()
    secret_fields: frozenset[str] = frozenset()
```

base 侧只有三步：`provider.surface()` → `resolve_plugins(project)`（继承 + 能力匹配）→ 合并 `Contribution` 交给统一骨架模板。

### 2.3 现有三类页面如何实现

| 页面 | capabilities | context(visitor) | context(plugin / ai) | items |
|------|--------------|------------------|----------------------|-------|
| space | `has_children, has_items, supports_layout` | 标题、简介、主题 | 同 visitor（只含可见子项标题） | `store.visible_projects()` 的子项 |
| blog（列表/文章） | `has_content, has_posts, has_items, supports_layout` | 博客信息；文章页加当前文章 | 标题/摘要/标签/正文节选（≤`_MAX_CONTEXT_BODY_CHARS`），草稿不出现 | 已发布文章 |
| resume | `has_content, is_personal_profile, has_items` | 模板渲染所用的公开字段 | 按插件隐私配置过滤（默认去掉 `email`/`phone`/`location`），同时注册 `plugin` 与 `ai` 指向同一份过滤上下文 | 工作/教育/项目段落 |

`mascot_chat._build_page_context` 中按 `project.type` 分支拼文本的逻辑，迁移后改为 `surface.context("ai")` 的通用序列化，从而 resume 自动获得看板娘对话能力且不泄露联系方式。

## 3. 配置与启停：分层继承

### 3.1 层级

```
全站默认 (site)  →  父空间 (space, 可多级, 深度<3)  →  当前页面 (space/blog/resume)
```

每层对每个插件的状态是三选一：

| 状态 | 含义 |
|------|------|
| `inherit`（缺省） | 沿用上一层的启停与配置 |
| `override` | 启用，并以本层 `config` 浅合并覆盖上一层 |
| `disabled` | 本层及（未再 override 的）下层关闭 |

存储格式（向后兼容现有 `content.extensions`）：

```json
"extensions": {
  "official.mascot": {"mode": "override", "config": {"character": "..."}, "cascade": true}
}
```

`cascade=false` 表示只作用于本页、不下传给子项。旧格式 `{installed, enabled, config}` 映射为：`enabled=true → override`，`enabled=false → disabled`，键缺失 → `inherit`。全站默认存在 `admin` 单行表新增的 `site_extensions` JSON 字段。

### 3.2 解析规则（只在 base 实现一次）

1. 沿 `parent_chain` 从 site 到当前页依次折叠状态，得到 `(enabled, config)`。
2. 校验 `manifest.requires ⊆ surface.capabilities` 且 `excludes ∩ capabilities = ∅`；不满足则视为不适用（不报错，管理台灰显并说明原因）。
3. `secret_fields` 只在声明它的层存储，下层继承时服务端合并、前端仅见“已设置”。
4. 管理台展示每个插件的“生效来源”（site / 某父空间 / 本页）。

## 4. 现状与差距

| 现状（代码事实） | 差距 |
|------------------|------|
| `Extension.targets` 写死 `blog/space/resume`；`PackExtension.pages` 写死 `list/post/space/resume` | 需改为 capability 声明，新增页面类型时插件不感知 |
| `Extension` 协议有 `render_list_context / render_post_context / render_space_context / render_resume_context` 等按页面类型命名的方法 | 收敛为单一 `contribute(surface, …)` |
| 扩展配置只存在各项目自己的 `content.extensions`，`normalize_extensions` 按 `target` 过滤，`{installed, enabled, config}` | 没有全站默认、没有父空间继承；子空间想要相同看板娘只能逐个配置 |
| `build_render_bundle` 只有 `start / main_start / end` 三个注入槽 + `list_card/post_header` 模板 | 缺 `aside / title_deco / icons / overlay` 等结构化槽，缺 tokens 与 items 通道，布局无法插件化 |
| 主题变量（`accent/font_family/radius_card`）是 `SpaceApp` 自己的字段；`resume_style` 是专属插件 | 主题应是写 `tokens` 的通用插件 |
| `mascot_chat._build_page_context` 按 `project.type` 分支直接读 `raw_content` | 插件认识页面类型、自行读私有数据；resume 无分支，无法接入；隐私边界在插件里 |
| `mascot.targets = ("blog","space")` | 简历看板娘无法启用 |
| 无访客写入能力，无审核队列 | 漂流瓶需要 `accepts_visitor_input` 与通用的待审存储/限频基础设施 |

## 5. 迁移步骤（每步独立可发布、测试全绿）

1. **引入契约，不改行为**：新增 `app/surface.py`（Protocol + dataclass），三类页面各实现 `surface()`；仅测试使用。
2. **AI 上下文改走 surface**：`mascot_chat` 使用 `surface.context("ai")`；补“简历 ai 上下文不含 email/phone”测试。
3. **能力位替代 targets**：`Extension` 增加 `requires`，由 `targets` 自动推导默认值；`normalize_extensions` 与 `active_extensions` 改用能力匹配。mascot 声明 `requires=set()` → 简历自动可用。
4. **新增结构化槽与 tokens**：`build_render_bundle` 输出 `slots/tokens`，旧 `start/main_start/end` 作为别名保留；骨架模板统一渲染槽位。
5. **`contribute()` 统一入口**：`BaseExtension.contribute` 默认调用旧的 `render_*_context`/`inject_html`，外部 pack 不受影响；内置插件逐个迁移后删除旧方法。
6. **分层继承**：`admin.site_extensions` + `mode/cascade`；读旧格式、写新格式；管理台显示生效来源。
7. **items + 布局插件**：surface 暴露 `items`，`supports_layout` 页面允许一个 `kind="layout"` 插件接管条目排布（默认网格作为内置布局）。
8. **访客输入基础设施**：通用 `visitor_submissions` 表（`project_id, plugin_id, payload, status=pending|approved|rejected, ip_hash, created_at`）+ 通用限频 + 管理台审核队列；仅在声明 `accepts_visitor_input` 的页面上可用，写入接口走独立的公开 API（非 `admin_api`），仍需同源校验。

## 6. 首批消费者

| 消费者 | 类型 | requires | 依赖步骤 | 要点 |
|--------|------|----------|----------|------|
| 大肥鱼主题包 | `theme` | 无 | 4、6 | 只写 tokens（色板、圆角、字体、图标集）+ `title_deco` 装饰；在全站默认层启用即全站生效，子空间可 disabled |
| 布局插件（瀑布流/时间线/书架） | `layout` | `has_items, supports_layout` | 7 | 只消费 `items`，不读页面私有数据 |
| 简历看板娘 | `interactive` | 无（复用 mascot） | 2、3 | 对话上下文来自 `context("ai")`，联系方式由 resume 过滤 |
| 漂流瓶空间 | `interactive` | `accepts_visitor_input`（新页面类型或空间子类型提供） | 8 | **先审后发**（投递进入 pending，管理员通过才可被捞）；**IP 限频**（按 `ip_hash`，如每 IP 每小时 3 投 / 30 捞）；**禁链接**（服务端拒绝含 URL/域名模式的内容，输出始终 Jinja 转义）；**投一捞一**（同一会话需先成功投递才能捞取一个随机、非本人的已审瓶子） |

## 7. 不变量（迁移全程保持）

- `AGENTS.md` 五条安全红线不变；插件输出 HTML 一律经 Jinja 模板转义，`Markup` 只来自插件自己的模板。
- 外部平台调用仍只走 `app/og.py`；LLM 调用沿用 `mascot_chat` 的端点校验。
- base 中不得出现具体插件 id 或页面类型字符串分支（可加一条测试 grep 守护）。
