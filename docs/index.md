# SiteFlow 文档索引

## 核心与用户文档

| 文档 | 内容 |
|------|------|
| [README.md](../README.md) | 英文主文档：功能全景、PageSurface 生态、快速开始、API 与环境变量 |
| [README_CN.md](../README_CN.md) | 简体中文主文档（与 `README.md` 100% 同步） |
| [CHANGELOG.md](../CHANGELOG.md) | 版本变更记录（Keep a Changelog） |

## 架构与设计文档

| 文档 | 内容 |
|------|------|
| [DESIGN.md](../DESIGN.md) | v1 产品与安全设计 |
| [DESIGN-v2.md](../DESIGN-v2.md) | v2 应用注册表、嵌套空间、简历与博客设计 |
| [PLUGIN_DESIGN.md](PLUGIN_DESIGN.md) | 已落地的 `PageSurface` 契约、分层继承、结构化插槽与访客提交架构 |
| [API_V1.md](API_V1.md) | Agent-Ready `/api/v1/*` REST 接口指南、细粒度令牌权限矩阵与 `curl` 示例 |
| [PLUGIN_IDEAS.md](PLUGIN_IDEAS.md) | 后续插件与扩展创意备忘（趣味交互、体验增强与架构延展，暂缓实施） |
| [product_research_and_plan.md](product_research_and_plan.md) | 产品深度调研与全景演进白皮书 |

## 工程协作与安全

| 文档 | 内容 |
|------|------|
| [AGENTS.md](../AGENTS.md) | 代码目录职责、开发命令、编码约定与安全红线 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献指南、零构建规范、Git/PR/CI 合并流程与插件包贡献指引 |
| [SECURITY.md](../SECURITY.md) | 私密安全漏洞上报策略 |
| [rules/index.md](rules/index.md) | 仓库工程规则细分索引（API、代码、Docker、文档） |

## 部署与运维

| 文档 | 内容 |
|------|------|
| [deployment.md](deployment.md) | Docker 部署、Nginx/Caddy 反向代理与 HTTPS 配置 |
| [operations.md](operations.md) | 数据备份、升级与故障排查 |
| [deploy/README.md](../deploy/README.md) | 服务器无源码镜像一键部署（`init.sh` / `stop.sh`） |

## 配套生态仓库

| 仓库 | 内容 |
|------|------|
| [mcocdaa/siteflow-plugins](https://github.com/mcocdaa/siteflow-plugins) | 官方零构建声明式插件包仓库（含 `dafeiyu_theme` 大肥鱼深海主题包、阅读进度条、代码块复制、空间/简历徽章） |
