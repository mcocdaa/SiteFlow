## 变更说明 (Description)
<!-- 请简要描述本次 PR 的改动内容、解决的痛点或实现的功能 -->

## 关联 Issue (Related Issue)
<!-- 例如 Fixes #123, Closes #456 -->

## 变更类型 (Type of Change)
- [ ] Bug 修复 (Bug fix)
- [ ] 新功能 (New feature)
- [ ] 文档更新 (Documentation update)
- [ ] 代码风格 / 重构 (Refactoring / Code style)
- [ ] 性能优化 (Performance improvement)
- [ ] 构建 / 配置 / CI (Build / CI / Chores)

## 验证与门禁核对 (Verification & Guardrails)
- [ ] 已运行 `./scripts/check.sh` 全绿（含 `uv lock --check`、`scripts/check_repo.py`、`pytest`、`ruff`、`mypy`、`node --check`）
- [ ] 已确认 `app/static/js/i18n.js` 中 `zh` / `en` 字典键 100% 对齐（无缺键、多余键、重复键）且模板/JS 引用一致
- [ ] 若变更依赖，已保持 `requirements.txt`、`requirements-dev.txt`、`pyproject.toml` 与 `uv.lock` 完全同步
- [ ] 已核对安全红线：`/projects/*` 保持 `CSP: sandbox`、ZIP 解压防穿越/软链/炸弹、管理写接口经过 `admin_api` 三重校验、改密立即失效旧会话、`PROJECTS_SANDBOX=false` 拒绝启动、外呼统一经 `app/og.py` 私网校验、模板与静态脚本零外部 CDN
- [ ] 若改动容器或编排配置，已验证 `ADMIN_PASSWORD=ci-secret docker compose config -q` 通过
- [ ] 文档与 `CHANGELOG.md` 已同步更新（如涉及接口、配置或版本发布变更）

## 其他说明 (Notes)
<!-- 如有特殊注意事项或对评审者的说明，请在此备注 -->
