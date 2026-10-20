---
name: easy-painter-release
description: Prepare or carry out an Easy Painter version release and production rollout. Use for requested version bumps, release tags, or production updates in this repository; do not use for ordinary feature work or local development.
---

# Easy Painter 发布

将请求的版本从可验证的工作树推进到可恢复的正式发布。先阅读仓库 `AGENTS.md`；涉及本次数据库、存储或数据行为变更时，再读取对应升级说明和 `docs/backup-and-disaster-recovery.md`。

## 发布前

- 从 `VERSION` 和 `CHANGELOG.md` 确认当前版本、目标版本和用户可感知变更。只用 `python3 scripts/version.py set vX.Y.Z` 同步版本；不要手改各 manifest。
- 运行与变更相称的检查：后端变更运行 `cd backend && uv run pytest`，前端变更运行 `cd frontend && npm run build`；始终运行 `python3 scripts/version.py check vX.Y.Z` 和 `python3 scripts/version.py notes vX.Y.Z`。
- 检查工作树和目标 tag，说明待提交文件、验证结果及未覆盖的生产风险。准备发布不等于已获准提交、打 tag、推送或部署。

## 获得正式发布授权后

1. 仅提交本次发布所需文件，创建并推送新的 `vX.Y.Z` tag；GitHub Release 由 tag 工作流生成，不手工创建。
2. 等待配套 backend、nginx 和 migrations 的同版本镜像构建成功；生产环境始终固定 `IMAGE_TAG=vX.Y.Z`，不能以 `main` 或 `sha-*` 作为常态发布版本。
3. 在生产操作前执行版本特定指南要求的备份、停写、迁移或数据检查。迁移期间不得混跑新旧 API、worker、dispatcher 或错误复用旧存储目录。
4. 使用已验证的正式 tag 更新服务，检查 readiness、迁移版本及本次功能的最小真实路径。记录实际部署版本和关键结果；不要把本地 mock/SQLite 测试描述成生产联调。

## 失败与回退

镜像、迁移、readiness 或关键 smoke check 未通过时停止扩大操作，保留日志和现状。按当前升级指南用上一个已验证 tag、与之匹配的 compose 和存储配置回退；不要删除数据、镜像、`.env` 或持久化目录来“重试”。

## 完成标准

交付中明确区分：代码/版本检查、tag 与 GitHub Release、镜像构建、生产部署和 smoke check 各自是否已完成；附带目标版本、验证证据、未覆盖风险与（如需要）具体回退点。
