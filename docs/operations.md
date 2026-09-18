# 运维

## 数据与备份

数据全部位于 `./data`（容器内 `/data`）：

```
data/
├── siteflow.db            # SQLite（WAL）
├── secret_key             # 会话签名密钥
├── projects/{slug}/...    # 作品文件
└── media/covers/*.webp    # 封面
```

备份：停止容器后整体拷贝 `data/`，或在线执行 `sqlite3 data/siteflow.db ".backup ..."`。

## 升级

```bash
git pull
./scripts/start.sh         # 重新构建并滚动替换容器
./scripts/stop.sh          # 停止
```

镜像升级不触碰挂载卷；`secret_key` 不变则管理员会话在重启后仍有效。

## 排障

| 现象 | 处理 |
|------|------|
| 启动报 `ADMIN_PASSWORD is required` | 在 `.env` 设置后重启 |
| 启动报 `PROJECTS_SANDBOX must stay true` | 不要设置 `PROJECTS_SANDBOX=false` |
| 容器 unhealthy | `docker logs siteflow`；检查 `/data` 是否可写（uid 1000） |
| 上传报 413 | 调大 `MAX_UPLOAD_MB`，同时同步反代 `client_max_body_size` |
| 页面样式/JS 404 | 静态文件随镜像发布，重建镜像 |

## 发布

```bash
git tag -a vX.Y.Z -m "SiteFlow vX.Y.Z"
git push origin vX.Y.Z
```

推送 tag 会触发 `.github/workflows/release.yml`：测试 → 构建并推送镜像到
`ghcr.io/mcocdaa/siteflow`（semver + latest）→ 自动创建 GitHub Release。
版本记录维护在 [CHANGELOG.md](../CHANGELOG.md)。

用户侧升级：

```bash
docker pull ghcr.io/mcocdaa/siteflow:latest
./scripts/stop.sh && ./scripts/start.sh
```
