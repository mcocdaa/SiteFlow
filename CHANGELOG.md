# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 应用（Application）：内置 `space` 空间，统一 `/projects/` 路由；核心不含具体插件，静态站点即普通 HTML/ZIP 项目
- 应用注册表 `app/plugins/`（AppPlugin 协议 + 插件模板目录自动加载）：`space` 作为第一个应用注册，管理台「应用」列表由注册表生成
- 管理台：新建按钮由应用列表生成、应用管理页（面包屑/子项/嵌套上传/深度限制）
- 嵌套上限 3 层；叶子类型禁止包含子项；删除级联清理文件；可见性沿祖先继承

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
