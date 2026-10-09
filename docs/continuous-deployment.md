# 正式版本自动部署

代码进入 `main` 后，按版本流程同步 `VERSION`、manifest 和 changelog，再推送新的 `vX.Y.Z` tag。`Container images` 工作流的三个镜像全部构建成功后，`deploy` job 自动部署。普通 `main` push 只构建镜像，不部署；正式 tag 必须指向 `main` 已包含的提交。

## 首次配置

在 GitHub 仓库 Settings → Environments 创建 `production`，只允许 `v*` tag 部署。不设置 required reviewers 即可在打 tag 后自动上线。在该环境添加 Secrets：

| Secret | 内容 |
| --- | --- |
| `DEPLOY_HOST` | GitHub runner 可访问的生产 SSH 主机 |
| `DEPLOY_PORT` | SSH 端口；留空默认 22 |
| `DEPLOY_USER` | 部署账号 |
| `DEPLOY_PATH` | 已有部署的绝对目录，包含 `.env`、`compose.yml`、`data/` |
| `DEPLOY_SSH_KEY` | 专用 SSH 私钥，对应公钥安装到生产部署账号 |
| `DEPLOY_KNOWN_HOSTS` | 经可信渠道核验的完整 known_hosts 行，非默认端口使用 `[host]:port` |

机器身份和密钥只保存在私有运维配置与 GitHub Secrets，不能写入仓库。脚本要求生产服务器安装 Bash、Docker Compose（支持 `up --wait`）、`flock`、GNU coreutils，部署账号可运行 Docker、写入部署目录。镜像私有时，服务器须预先登录 GHCR。应用凭证仍仅保存在生产 `.env`，不上传 GitHub。

GitHub 托管 runner 必须能直连 SSH；内网、跳板机或来源 IP 白名单环境须先解决连接方式，不能仅填写本地 SSH 别名。首次启用前，确认当前部署固定正式版本 tag，并先验证隔离环境。

## 部署行为

- GitHub concurrency 与服务器 `flock` 串行化部署；版本比较阻止过时构建覆盖新版本。重复运行同一 tag 可用于恢复。
- 拉取全部镜像后，保存旧 `.env`、Compose 与经过 `pg_restore` 解析校验的数据库快照，权限仅限部署账号，目录为 `backups/deploy-<UTC时间>-<tag>/`。不自动删除备份，运维应监控磁盘容量。
- 停止 nginx、API、dispatcher，然后给 worker 最多 750 秒正常退出，再执行 Flyway 和启动同版本服务。期间有维护窗口；超出等待时间的 worker 会由 Docker 强制停止，既有 watchdog 处理遗留任务。
- 成功必须满足 Compose 健康检查、API readiness（包含 schema 和 dispatcher）、worker ping 与 nginx readiness 转发。
- 失败时 GitHub job 标记失败并留下恢复路径。迁移向前执行，不自动降级 schema；若服务停下后失败，可能保持停机或部分启动状态，需要维护者处理。

此次内置快照只有数据库和部署配置，不是完整灾难恢复快照。涉及存储迁移、保留策略或破坏性数据变化的版本，必须先按该版本指南完成完整备份及停写检查，再推送 tag；参考[生产备份与灾难恢复](backup-and-disaster-recovery.md)。

## 恢复与审计

在 Actions 查看 `Deploy production release` job 和 `production` 环境部署记录。首次上线与 UI 变更仍需真实浏览器功能验收，readiness 不代表生图上游联调成功。

无 schema 或存储变更时，可在服务器用原正式 tag 与保存的 Compose 恢复；不要把旧 tag 当新版本重复发布。涉及迁移时，按版本指南评估兼容性或使用完整快照恢复，不直接覆盖数据库。修复连接或环境问题后可重新运行失败的 tag 工作流。
