# SiteFlow v2 设计：应用（Application）与插件

> 状态：v2.0 已实施（2026-09-18），v2.1 起为规划。
> v1 方案见 [DESIGN.md](DESIGN.md)，本文件只描述 v2 增量。

## 1. 主题与目标

让 SiteFlow 从"作品卡片墙"升级为"个人网站容器"：根画廊仍是卡片 index，但每张卡片可以指向
一个**应用**——它拥有自己的空间（子卡片）、静态站点或插件页面（简历等），用于展示个人简历、
空间、博客等。管理员账号全局唯一。

v2.0 交付：应用模型 + 静态子站 + 空间（嵌套卡片）+ 插件框架 + 简历插件（管理台内编辑）。
v2.1 交付：博客插件 + 主题/外观。v2.2 交付：2FA 登录 + 管理台增强。

### 非目标（v2.0）

- 多管理员/注册/权限系统（管理员始终唯一）
- 外部插件市场与热加载（仅预留加载入口）
- 富文本/HTML 编辑（简历字段为纯文本，转义输出）
- 应用级独立主题（v2.1）

## 2. 概念模型

| 概念 | 说明 |
|------|------|
| 应用 Application | 一张卡片背后的东西；有类型，可包含子项或由插件渲染 |
| 空间 space | 应用的一种：自动生成的卡片 index，列出其子项（类似嵌套的根画廊） |
| 静态站点 site | 应用的一种：上传 HTML/ZIP，入口经 CSP sandbox 渲染；叶子节点 |
| 简历 resume | 插件应用：由插件渲染的页面，内容存 SQLite 并在管理台编辑；叶子节点 |
| 层级 depth | 根=1，应用=2，应用的子项=3；深度 3 的项不能再建应用 |

规则：

1. 所有条目（含应用）在同一张表，`parent_id` 为 NULL 表示根画廊条目。
2. `space` 可包含：html / zip / link / space / site / resume（受深度限制）。
3. `site` 与 `resume` 为叶子，不能包含子项。
4. 深度 3 的 `space` 不能再创建子应用，只能放 html/zip/link。
5. slug 全局唯一（沿用现有逻辑），路由不体现层级，避免歧义与迁移复杂度。

## 3. 数据模型

在 `projects` 表上增量扩展（SQLite）：

| 列 | 类型 | 说明 |
|----|------|------|
| `parent_id` | INTEGER NULL | 自引用外键，NULL=根；删除父级级联删除子级 |
| `content` | TEXT NOT NULL DEFAULT '{}' | 插件数据/空间配置 JSON（简历内容等） |

`type` 取值扩展为：`html` `zip` `link`（原有） + `space` `site` `resume`（应用）。
`site` 复用现有上传/解压管线（`entry`、文件目录不变）。

迁移：`store.init()` 启动时检测列缺失并 `ALTER TABLE ... ADD COLUMN`（无需新依赖）。
排序与置顶在**同一父级内**生效：`next_sort_order(db, parent_id)`、`move` 按兄弟节点交换重排。

存储路径（与 v1 一致，仅新增 DB 列）：

```
data/
├── projects/{slug}/...          # html/zip/site 文件
└── media/covers/{slug}.webp     # 封面、简历头像
```

## 4. 路由

所有条目统一在 `/projects/` 命名空间下：**应用本身也是 project**，slug 全局唯一，URL 不体现层级。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 根画廊（卡片 index，含应用卡片） |
| GET | `/projects/{slug}/` | 按类型分发：`html/zip/site` → 302 到 `entry`；`space` → 渲染应用卡片 index；`resume` → 插件渲染简历页 |
| GET | `/projects/{slug}/{path}` | 静态文件（仅 html/zip/site，`CSP: sandbox` + nosniff） |
| POST/PATCH/DELETE | `/api/admin/projects...` | 应用与子项的创建/内容/排序/显隐/删除（`admin_api` 三重校验） |

说明：

- 卡片跳转：html/zip → `/projects/{slug}/`；link → 外站；space/site/resume → `/projects/{slug}/`。
- `space` 的 index 由我们的模板渲染（非 sandbox），与根画廊同一设计语言，可继续点入子项。
- 静态文件处理与 v1 共用同一函数与媒体类型表，响应必须带 `CSP: sandbox`。
- 可见性继承：任一祖先 `visible=0`，后代对访客 404。

## 5. 插件机制

```
app/plugins/
├── __init__.py
├── base.py        # AppPlugin 协议/数据类
├── registry.py    # 内置注册表 + 预留外部入口
└── resume/
    ├── plugin.py  # 插件实现（渲染 + 默认内容 + 校验）
    └── admin.py   # 该插件的管理接口（admin router）

插件页面模板统一放 `app/templates/`（共享 Jinja 环境，如 `resume.html`）。
```

接口（`base.py`）：

```python
class AppPlugin(Protocol):
    type: str                       # "resume"
    label: str                      # 管理台显示名
    icon: str                       # Lucide 图标名
    leaf: bool                      # True 不可包含子项

    def default_content(self) -> dict: ...
    def validate_content(self, raw: str) -> dict: ...   # 抛 InvalidContent
    def render(self, request, project, db) -> Response: ...
    def register_admin(self, router) -> None: ...       # 管理接口挂载
```

- 注册：`registry.register(ResumePlugin())`；启动时遍历 `APPS` 生成管理台"新建应用"选项。
- 预留外部加载：`importlib.metadata.entry_points(group="siteflow.apps")`（v2.0 不开放文档）。
- 插件管理路由统一挂在应用上下文：`/api/admin/projects/{id}/content`（PATCH 内容）、
  `/api/admin/projects/{id}/...`（插件自定义子路由）。

## 6. 简历插件（v2.0）

数据采用开源标准 [JSON Resume](https://jsonresume.org/schema/) 的子集（字段名兼容，便于未来复用
开源主题与导出），存于 `projects.content`：

```json
{
  "basics": {
    "name": "张三",
    "label": "后端工程师",
    "image": "avatar.webp",
    "email": "a@b.c",
    "phone": "",
    "url": "https://example.com",
    "summary": "一句话简介，可多行",
    "location": {"city": "深圳", "region": "", "countryCode": "CN"},
    "profiles": [{"network": "GitHub", "username": "x", "url": "https://github.com/x"}]
  },
  "work": [{"name": "公司", "position": "职位", "url": "", "startDate": "2022-07", "endDate": "至今", "summary": "", "highlights": ["要点1"]}],
  "education": [{"institution": "学校", "area": "专业", "studyType": "本科", "startDate": "", "endDate": ""}],
  "projects": [{"name": "项目", "description": "", "highlights": [], "keywords": [], "url": ""}],
  "skills": [{"name": "Python", "keywords": ["FastAPI"]}]
}
```

- v2.0 只实现上述 5 个区段；其余 JSON Resume 区段（volunteer/awards/languages 等）后续按需加入。
- 字段全部纯文本，Jinja 转义输出；URL 只允许 http(s) 或站内相对路径。
- 渲染：单页、最大宽度 800px、时间线样式、深浅色自适应、`@media print` 打印友好（提供"打印 / 导出 PDF"按钮，走浏览器原生打印）。
- 管理台编辑：基本信息表单 + 各区段条目增删改/上下移；头像复用封面上传管线（`media/covers/`）。
- 简单优先：不做 Markdown/富文本、不做多套主题（主题在 v2.1）。

## 7. 管理台

- 根列表新增按钮：`新建应用` → 选择类型（空间 / 静态站点 / 简历）。
- 应用行操作：`进入`（空间 → 子项列表；简历 → 编辑器；静态站点 → 替换/查看）。
- 应用管理页 `/admin/projects/{id}`：面包屑（根 / 应用 / 子项）、子项 CRUD（复用现有行操作）、
  深度提示（>=3 层隐藏"新建应用"）。
- 所有既有交互不变：拖拽上传、外链、封面、Pin、上移/下移、显隐、删除（父级删除级联子项与文件）。

## 8. 安全规则（红线）

1. `site` 应用与嵌套静态文件继续带 `CSP: sandbox ...`（`views.SANDBOX_CSP`）。
2. `space`/`resume` 页面由我们的模板渲染，不进入 sandbox，但所有用户内容必须转义。
3. 应用创建/移动必须服务端校验：父级必须是自己的 `space`、父级深度 < 3、禁止移动到自身后代。
4. 所有写接口继续走 `admin_api`（登录 + 同源 + CSRF），上传继续走 `uploads` 安全管线。
5. slug 全局唯一；删除父级级联清理 DB 行与磁盘目录（幂等）。
6. 隐藏继承：祖先不可见时，所有后代路由对访客 404（含静态文件与插件页）。

## 9. 验收标准（v2.0）

- [ ] 根画廊可新建三种应用，卡片正确区分类型并带图标。
- [ ] 空间应用 `/projects/{slug}/` 显示子卡片；可上传 html/zip、加外链、再建子应用。
- [ ] 静态站点应用上传 ZIP/HTML 后正常渲染，响应带 CSP sandbox；与普通 html/zip 卡片互不影响。
- [ ] 简历应用：管理台编辑基本信息与章节条目，页面即时反映；打印样式正常。
- [ ] 深度限制：根→应用→应用 可建；第 4 层拒绝（前端隐藏 + 后端 400）。
- [ ] 叶子（site/resume）不允许添加子项（后端拒绝）。
- [ ] 空间内 Pin/排序互不影响根画廊与其他空间。
- [ ] 删除空间应用级联删除子项与文件；隐藏祖先使后代对访客 404。
- [ ] 未登录/缺 CSRF 的管理请求 401/403；不存在的 slug 404。
- [ ] 现有 23 项测试全绿 + v2 新增测试（嵌套/深度/级联/插件/转义）。

## 10. 版本路线

| 版本 | 内容 |
|------|------|
| v2.0 | 应用模型（space/site/resume）、插件框架、简历插件、管理台嵌套 |
| v2.1 | 博客插件（文章列表/详情/标签可选）、主题与外观（应用级标题/图标/主题色/布局） |
| v2.2 | 2FA 登录（TOTP）、管理台增强（全局搜索/审计信息等） |
