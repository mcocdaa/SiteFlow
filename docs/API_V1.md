# SiteFlow API v1 接入指南

SiteFlow `/api/v1/*` 是面向通用 AI Agent、CLI 工具与 CI/CD 流水线的统一 REST 接口，提供**细粒度可吊销令牌**、**作用域隔离**、**鉴权 OpenAPI 3.1 自发现**，以及覆盖项目树、博客写作与插图、结构化内容（简历/空间/漂流瓶）、静态 HTML/ZIP 幂等部署、扩展配置与访客审核的完整闭环。

## 认证方式

所有 `/api/v1/*` 接口均支持以下两种无状态令牌传递方式（无需 CSRF 校验）：

- `Authorization: Bearer <token>`
- `X-API-Key: <token>`

SiteFlow 支持三类身份主体（`principal.kind`）：

| 类型 | 凭证形式 | 说明 |
|------|----------|------|
| `db_token` | `sft_...`（推荐） | 在管理后台 `/admin` 顶栏 **API 令牌** 弹窗或 `POST /api/v1/tokens` 签发；支持细粒度 Scope、限定项目作用域、过期时间与随时吊销 |
| `env_token` | 环境变量 `SITEFLOW_API_TOKEN` | 全站全权主令牌（`is_admin: true`），适用于可信运维脚本或兼容既有无头部署流程 |
| `session` | 管理员登录 Cookie | 浏览器管理员会话，需同时携带同源 `Origin` 与 `X-CSRF-Token` |

### 统一错误格式与缓存策略

- 所有 `/api/v1/*` 响应强制附带 `Cache-Control: no-store`，防止代理或客户端缓存敏感接口数据。
- 业务错误返回结构化 JSON：

```json
{
  "ok": false,
  "code": "forbidden_scope",
  "error": "当前令牌缺少所需权限：posts:write",
  "hint": "请使用具备 posts:write 或 admin 权限的令牌"
}
```

- 请求参数校验失败（HTTP `422`）返回：

```json
{
  "ok": false,
  "code": "validation_error",
  "error": "请求参数校验失败",
  "details": [],
  "hint": "请检查字段名与类型，或查看 GET /api/v1/openapi.json"
}
```

## Agent 自发现（首步推荐）

Agent 拿到令牌后，推荐先调用 `whoami` 确认自身权限与可操作项目范围，再按需读取鉴权 `openapi.json` 获取完整字段定义：

```bash
export SITEFLOW_URL="http://127.0.0.1:8000"
export SITEFLOW_TOKEN="sft_你的令牌明文"

# 1. 查看当前令牌身份、权限 Scope 与允许的项目作用域
curl -sS "$SITEFLOW_URL/api/v1/whoami" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN"

# 2. 获取 /api/v1/* 完整 OpenAPI 3.1 Schema（需要 read 权限）
curl -sS "$SITEFLOW_URL/api/v1/openapi.json" \
  -H "X-API-Key: $SITEFLOW_TOKEN"
```

`GET /api/v1/whoami` 返回示例：

```json
{
  "ok": true,
  "api_version": "1",
  "site_title": "SiteFlow",
  "principal": {
    "kind": "db_token",
    "is_admin": false,
    "scopes": ["posts:write", "read"],
    "allowed_slugs": ["tech-space"],
    "token_id": 3,
    "name": "博客写作 Agent",
    "prefix": "sft_AbCdEf12"
  }
}
```

> 根路径 `/docs`、`/redoc` 与 `/openapi.json` 默认保持关闭（返回 404）；仅经过认证的 `GET /api/v1/openapi.json` 暴露 `/api/v1/*` 契约。

## 权限 Scope 与作用域说明

| Scope | 说明 |
|-------|------|
| `read` | 只读访问：查看项目列表/详情、结构化内容、博客文章、扩展状态、访客投稿与 `GET /api/v1/openapi.json` |
| `posts:write` | 博客文章与媒体：新建/幂等更新/局部修改/删除博客文章，以及上传博客正文插图、封面与背景图 |
| `content:write` | 结构化内容编辑：通过 `PATCH /api/v1/projects/{slug}/content` 局部更新简历、空间主题、漂流瓶配置等 |
| `projects:write` | 项目生命周期管理：创建应用/外链、修改元信息、移动父空间、删除项目以及上传/清除封面 |
| `deploy:write` | 静态制品部署：通过 `PUT /api/v1/projects/{slug}/deploy` 幂等发布或更新单文件 HTML 或多文件 ZIP 站点 |
| `submissions:write` | 访客提交审核：审核通过、拒绝或删除漂流瓶等访客投稿 |
| `extensions:write` | 扩展插件配置：启用/停用/覆写项目级扩展插件配置（密钥仅服务端合并，不回传明文） |
| `admin` | 完全管理：覆盖全部 Scope；当且仅当同时未限定项目（`allowed_slugs` 为空）时 `is_admin=true`，可管理 API 令牌、修改项目密码与访问 `/api/admin/*` |

**作用域（`allowed_slugs`）继承规则**：

- `allowed_slugs` 为空列表 `[]` 表示**全站生效**。
- 指定某个**空间（`space`）的 `slug`**，将自动允许访问该空间及其全部后代子空间与子项目（最多 3 层嵌套）。
- 受限令牌新建、部署或移动项目时，目标项目及其父空间均须位于 `allowed_slugs` 范围内，否则返回 `403 forbidden_project`。

## 端点速查

| 分类 | 方法与路径 | 所需 Scope | 说明 |
|------|------------|------------|------|
| 自发现 | `GET /api/v1/whoami` | 任意有效令牌 | 查看当前主体、Scopes 与 `allowed_slugs` |
| 自发现 | `GET /api/v1/openapi.json` | `read` | 获取仅含 `/api/v1/*` 的 OpenAPI 3.1 Schema |
| 项目 | `GET /api/v1/projects` | `read` | 支持 `view=flat\|tree`、`type`、`parent_slug` 筛选，自动按作用域过滤 |
| 项目 | `POST /api/v1/projects/app` | `projects:write` | 创建内置应用（`space`/`blog`/`resume`/`bottle`），返回 `201` |
| 项目 | `POST /api/v1/projects/link` | `projects:write` | 创建外链作品（自动抓取 OG 与封面），返回 `201` |
| 项目 | `GET /api/v1/projects/{slug}` | `read` | 获取项目摘要、脱敏内容、子项列表与近 7 日访问统计 |
| 项目 | `PATCH /api/v1/projects/{slug}` | `projects:write` | 局部更新标题、描述、外链、可见性、置顶、父空间；修改 `password` 额外需 `admin` |
| 项目 | `DELETE /api/v1/projects/{slug}` | `projects:write` | 级联删除项目、子项、文件、统计与投稿记录 |
| 封面 | `POST /api/v1/projects/{slug}/cover` | `projects:write` | 上传自定义封面（最大 10MB） |
| 封面 | `DELETE /api/v1/projects/{slug}/cover` | `projects:write` | 清除封面并恢复默认过程式 SVG 封面 |
| 内容 | `GET /api/v1/projects/{slug}/content` | `read` | 读取结构化 JSON 内容（扩展密钥自动脱敏） |
| 内容 | `PATCH /api/v1/projects/{slug}/content` | `content:write` | 传入 JSON 对象局部合并更新结构化内容，保留未提及字段与扩展密钥 |
| 部署 | `PUT /api/v1/projects/{slug}/deploy` | `deploy:write` | 幂等上传或更新 `.html`/`.htm`/`.zip` 静态作品 |
| 博客 | `GET /api/v1/blogs/{slug}/posts` | `read` | 列出文章（默认省略正文，支持 `tag`、`q`、`include_body=true`） |
| 博客 | `POST /api/v1/blogs/{slug}/posts` | `posts:write` | 创建新文章（`201`），`slug` 冲突返回 `409 post_slug_exists` |
| 博客 | `GET /api/v1/blogs/{slug}/posts/{post_slug}` | `read` | 读取单篇完整文章（含正文与 `meta`） |
| 博客 | `PUT /api/v1/blogs/{slug}/posts/{post_slug}` | `posts:write` | 幂等创建或覆盖更新文章（新建 `201`，更新 `200`） |
| 博客 | `PATCH /api/v1/blogs/{slug}/posts/{post_slug}` | `posts:write` | 真局部修改（仅更新传入字段，支持 `new_slug` 改链接标识） |
| 博客 | `DELETE /api/v1/blogs/{slug}/posts/{post_slug}` | `posts:write` | 删除文章并自动清理不再被引用的正文与封面图片 |
| 博客 | `POST /api/v1/blogs/{slug}/media` | `posts:write` | 上传博客图片（`kind=image\|cover\|bg`，最大 10MB），返回 `url` 与 `markdown` |
| 扩展 | `GET /api/v1/projects/{slug}/extensions` | `read` | 查看项目已解析的三层扩展目录与脱敏配置 |
| 扩展 | `PUT /api/v1/projects/{slug}/extensions/{ext_id}` | `extensions:write` | 设置扩展模式（`inherit`/`override`/`disabled`）、`cascade` 与配置 |
| 审核 | `GET /api/v1/projects/{slug}/submissions` | `read` | 查看访客提交记录与分类计数（支持 `status`/`plugin_id`/`limit`/`offset`） |
| 审核 | `POST /api/v1/projects/{slug}/submissions/{sub_id}/status` | `submissions:write` | 审核操作：`approve` / `reject` / `pending` / `delete` |
| 令牌 | `GET /api/v1/tokens` | `admin` | 列出全部已签发令牌元数据（不含哈希与明文） |
| 令牌 | `POST /api/v1/tokens` | `admin` | 签发新令牌（`201`），仅此次响应返回 `plaintext` |
| 令牌 | `DELETE /api/v1/tokens/{token_id}` | `admin` | 吊销令牌并使其立即失效 |

## 常见任务实战示例

### 1. 查询目录树与筛选项目

```bash
# 获取嵌套目录树
curl -sS "$SITEFLOW_URL/api/v1/projects?view=tree" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN"

# 仅列出全部博客项目（扁平视图）
curl -sS "$SITEFLOW_URL/api/v1/projects?view=flat&type=blog" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN"
```

### 2. 博客写作、插图上传、幂等发布与局部修改

```bash
# 2.1 上传正文插图（kind 可选 image / cover / bg）
curl -sS -X POST "$SITEFLOW_URL/api/v1/blogs/my-blog/media" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -F "file=@./architecture.png" \
  -F "kind=image"
# 返回示例：{"ok": true, "url": "/media/blog/my-blog/image-xxxx.webp", "markdown": "![](/media/blog/my-blog/image-xxxx.webp)"}

# 2.2 POST 新建文章（首次返回 201，若 slug 已存在返回 409 post_slug_exists）
curl -sS -X POST "$SITEFLOW_URL/api/v1/blogs/my-blog/posts" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "零信任沙箱实践笔记",
    "slug": "zero-trust-sandbox",
    "tags": ["架构", "安全"],
    "summary": "介绍静态制品的 CSP 沙箱隔离方案。",
    "body": "## 背景\n\n![架构图](/media/blog/my-blog/image-xxxx.webp)\n\n正文内容……"
  }'

# 2.3 PUT 幂等发布 / 重放更新（首次 201 created=true，重复调用 200 created=false）
curl -sS -X PUT "$SITEFLOW_URL/api/v1/blogs/my-blog/posts/weekly-report-2026-w48" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "2026 第 48 周工程周报",
    "tags": ["周报"],
    "summary": "本周完成 API v1 与细粒度令牌管理。",
    "body": "### 本周进展\n\n- 上线 `/api/v1/*` 统一接口"
  }'

# 2.4 PATCH 局部修改标题与标签（正文、日期、摘要与扩展 meta 完整保留）
curl -sS -X PATCH "$SITEFLOW_URL/api/v1/blogs/my-blog/posts/weekly-report-2026-w48" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "2026 第 48 周工程周报（修订版）",
    "tags": ["周报", "API"]
  }'

# 2.5 按标签或关键词检索文章（默认不含正文，节省上下文；传 include_body=true 返回正文）
curl -sS "$SITEFLOW_URL/api/v1/blogs/my-blog/posts?tag=API&q=令牌" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN"
```

> 当文章被删除或更新后不再引用某张 `/media/blog/{slug}/...` 正文插图时，服务端会自动回收磁盘上失引的图片文件。

### 3. 简历与空间结构化内容局部更新

直接提交 JSON 对象即可，无需把 JSON 序列化成字符串；服务端自动合并 `basics` / `ai_visibility`，保留已有头像、既有扩展配置与密钥：

```bash
# 更新简历简介与城市（保留既有工作经历、头像、隐私设置与扩展配置）
curl -sS -X PATCH "$SITEFLOW_URL/api/v1/projects/my-resume/content" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "basics": {
      "label": "首席系统架构师",
      "location": {"city": "上海"}
    }
  }'

# 更新空间主题背景色（保留空间内其他插件配置）
curl -sS -X PATCH "$SITEFLOW_URL/api/v1/projects/ai-space/content" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "accent": "#4f46e5"
  }'
```

### 4. 静态 HTML / ZIP 幂等部署

```bash
# 首次部署返回 created=true；后续重复部署原子替换目录并保留原 visible 状态
curl -sS -X PUT "$SITEFLOW_URL/api/v1/projects/nightly-eval/deploy" \
  -H "Authorization: Bearer $SITEFLOW_TOKEN" \
  -F "file=@./report.zip" \
  -F "title=Nightly Eval Report" \
  -F "description=自动评测报告归档" \
  -F "parent_slug=ai-space"
```

### 5. 令牌签发与吊销

除在管理台 `/admin` 顶栏 **API 令牌** 弹窗进行可视化管理外，拥有全站 `admin` 权限的令牌也可以通过 API 签发与吊销：

```bash
# 签发仅限 tech-space 空间下博客写作的 30 天令牌
curl -sS -X POST "$SITEFLOW_URL/api/v1/tokens" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "技术专栏写作 Agent",
    "scopes": ["read", "posts:write"],
    "allowed_slugs": ["tech-space"],
    "expires_at": "2026-12-31T23:59:59Z"
  }'

# 查看全部令牌（绝不含明文或哈希）
curl -sS "$SITEFLOW_URL/api/v1/tokens" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 立即吊销指定令牌
curl -sS -X DELETE "$SITEFLOW_URL/api/v1/tokens/3" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## 安全红线与最佳实践

1. **最小权限签发**：为每个 Agent 签发独立令牌，只授予必需的 Scope（例如写作仅给 `read` + `posts:write`）并限定目标博客或父空间 `allowed_slugs`，建议设置 7/30/90 天有效期。
2. **哈希存储与一次明文**：数据库 `api_tokens` 表仅持久化 SHA-256 哈希与前 12 位前缀（`sft_...`），完整明文只在创建响应中返回一次。
3. **管理接口硬隔离**：任何非全站 `admin` 的 DB 令牌（包含低权令牌或限定了 `allowed_slugs` 的 `admin` 令牌）访问 `/api/admin/*` 均会被服务端 `403` 拦截；通过 `PATCH /api/v1/projects/{slug}` 修改项目访问密码也额外要求 `admin` 权限。
4. **作用域逃逸防护**：受限令牌无法通过 `POST /projects/app`、`POST /projects/link`、`PUT /deploy` 或 `PATCH parent_slug` 在授权作用域外创建或迁出项目。
5. **密钥零泄露**：所有内容与扩展读取接口均自动脱敏 `secret_fields`，绝不向 Agent 或浏览器返回明文密钥。
