# 生产备份与灾难恢复快速指南

本文只说明 Easy Painter 当前备份包含什么、如何判断快照可用，以及拿到备份数据后如何恢复服务。机器地址、用户名、网络拓扑、SSH 跳板和密钥分发方式不属于仓库文档，统一由仓库外的私有运维配置管理。

## 1. 当前备份情况

仓库提供 [`scripts/backup-production.sh`](../scripts/backup-production.sh)，由独立备份环境主动拉取生产数据。脚本实现了以下策略：

| 数据 | 备份方式 | 恢复用途 |
| --- | --- | --- |
| PostgreSQL | 每次生成一份 custom-format `pg_dump` 全量逻辑快照 | 恢复账号、任务、账务、配置和业务状态 |
| MinIO | rsync `--link-dest` 硬链接增量快照 | 恢复生成图片、参考图和对象元数据 |
| `.env`、`compose.yml` | 每个快照独立保存，文件权限为 `600` | 还原服务配置和容器编排 |
| Redis | 不备份 | 恢复时使用空 Redis，避免重复执行旧队列任务 |

### 一致性保证

- PostgreSQL 使用单事务一致性视图和 `--serializable-deferrable`，不复制运行中的 `data/postgres`。
- 脚本先完成并校验数据库快照，再复制 MinIO。应用先把图片写入 MinIO，随后才把任务标记为成功，因此数据库已引用的成功图片应包含在后续对象快照中。
- MinIO 临时上传目录和未完成 multipart 数据不会进入快照。
- 数据库归档会完整交给 `pg_restore` 解压解析到 `/dev/null`，再生成 SHA-256 校验文件；验证过程不会修改生产数据库。
- 所有步骤成功后，临时目录才会原子改名为正式快照并更新 `latest`。`.partial-*` 不是可恢复快照。
- 默认保留最新 30 个成功快照；开始备份前要求至少还有 2 GiB 可用空间。

### 快照结构

```text
<backup-root>/
├── latest -> snapshots/<snapshot-id>
└── snapshots/
    └── <snapshot-id>/
        ├── manifest.txt
        ├── config/
        │   ├── .env
        │   └── compose.yml
        ├── database/
        │   ├── easy_painter.dump
        │   └── easy_painter.dump.sha256
        └── minio/
```

每个 `<snapshot-id>` 目录在逻辑上都是一份完整快照。MinIO 文件可能与其他快照共享硬链接，因此不要在快照内部编辑文件。

### 如何确认现有备份可用

仓库中存在脚本不代表定时任务正在成功运行。恢复前必须在持有备份数据的环境中检查实际快照：

```bash
BACKUP_ROOT=/path/to/backup-root
SNAPSHOT_DIR=$(readlink -f "$BACKUP_ROOT/latest")

test -f "$SNAPSHOT_DIR/manifest.txt"
test -f "$SNAPSHOT_DIR/config/.env"
test -f "$SNAPSHOT_DIR/config/compose.yml"
test -f "$SNAPSHOT_DIR/database/easy_painter.dump"
test -d "$SNAPSHOT_DIR/minio"

cat "$SNAPSHOT_DIR/manifest.txt"
(
  cd "$SNAPSHOT_DIR/database"
  sha256sum -c easy_painter.dump.sha256
)
```

确认以下条件后才能把它作为恢复点：

- `SNAPSHOT_DIR` 指向正式快照目录，而不是 `.partial-*`。
- SHA-256 返回 `OK`。
- `manifest.txt` 的创建时间符合期望 RPO。
- `config/`、`database/` 和 `minio/` 都存在且可读。
- 持有备份的文件系统没有 I/O 或容量告警。

如果每日任务持续成功，计划 RPO 不超过约 24 小时。RTO 尚未经过正式隔离恢复演练，不能仅依据文档估算。

## 2. 从快照恢复服务

优先恢复到一台新服务器和空数据目录。不要直接覆盖仍在运行的旧生产环境；如需保留事故现场，应先隔离旧实例，避免新旧服务同时消费任务或对外提供流量。

### 2.1 准备恢复环境

恢复目标需要：

1. Docker Engine 与 Docker Compose。
2. 一个能够运行 Docker、接收备份文件的系统账号。
3. 到镜像仓库的访问权限。
4. 一条从备份数据所在环境到恢复目标的安全传输链路。
5. 已按上一节验证通过的正式快照。

以下命令在持有备份数据的环境中执行。先设置变量；具体值只保存在私有运维环境，不要写回仓库：

```bash
BACKUP_ROOT=/path/to/backup-root
SNAPSHOT_DIR=$(readlink -f "$BACKUP_ROOT/latest")
RECOVERY_HOST=operator@recovery-host
RECOVERY_DIR=/srv/easy-painter
SSH_KEY=/path/to/recovery-key
```

再次校验数据库归档：

```bash
(
  cd "$SNAPSHOT_DIR/database"
  sha256sum -c easy_painter.dump.sha256
)
```

### 2.2 恢复配置与 MinIO

在恢复目标创建空目录：

```bash
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "mkdir -p '$RECOVERY_DIR/data/minio' '$RECOVERY_DIR/data/redis'"
```

复制 `.env` 和 `compose.yml`。`.env` 包含真实密钥，传输完成后必须保持 `600`：

```bash
rsync -pt -e "ssh -i $SSH_KEY -o IdentitiesOnly=yes" \
  "$SNAPSHOT_DIR/config/.env" \
  "$SNAPSHOT_DIR/config/compose.yml" \
  "$RECOVERY_HOST:$RECOVERY_DIR/"

ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "chmod 600 '$RECOVERY_DIR/.env' '$RECOVERY_DIR/compose.yml'"
```

确保恢复目标的 MinIO 尚未启动，再把对象快照复制到已确认的空目录：

```bash
rsync -rlpt --delete \
  -e "ssh -i $SSH_KEY -o IdentitiesOnly=yes" \
  "$SNAPSHOT_DIR/minio/" \
  "$RECOVERY_HOST:$RECOVERY_DIR/data/minio/"
```

`--delete` 会删除目标目录中源快照不存在的文件。只有在 `RECOVERY_DIR` 和 `data/minio` 已确认属于新恢复环境时才能执行。

### 2.3 恢复 PostgreSQL

先拉取镜像并只启动空 PostgreSQL：

```bash
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "cd '$RECOVERY_DIR' && \
   docker compose -f compose.yml pull && \
   docker compose -f compose.yml up -d postgres"
```

等待 PostgreSQL 返回 `accepting connections`：

```bash
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "cd '$RECOVERY_DIR' && \
   docker compose -f compose.yml exec -T postgres sh -c \
   'pg_isready -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'"
```

把 custom-format dump 通过 SSH 标准输入恢复到空数据库：

```bash
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "cd '$RECOVERY_DIR' && \
   docker compose -f compose.yml exec -T postgres sh -c \
   'exec pg_restore -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" \
     --clean --if-exists --no-owner --no-acl --exit-on-error'" \
  < "$SNAPSHOT_DIR/database/easy_painter.dump"
```

`easy_painter.dump` 不是原始 `PGDATA`。不要解压或覆盖到 `data/postgres`，也不要对正在提供服务的数据库执行恢复。

### 2.4 运行迁移并启动其余服务

先启动恢复后的 MinIO，再执行 bucket 初始化和 Flyway forward-only migration：

```bash
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "cd '$RECOVERY_DIR' && \
   docker compose -f compose.yml up -d minio && \
   docker compose -f compose.yml run --rm --no-deps minio-init && \
   docker compose -f compose.yml run --rm --no-deps migrate && \
   docker compose -f compose.yml up -d --remove-orphans"
```

Redis 会以空状态启动。恢复点中的 queued/processing 任务可能由 outbox 重新投递，或由 watchdog 标记失败并退款；不要导入旧 Redis AOF 来“补任务”。

### 2.5 恢复验收

先检查容器和健康接口：

```bash
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$RECOVERY_HOST" \
  "cd '$RECOVERY_DIR' && docker compose -f compose.yml ps"

BASE_URL=https://recovery.example.com
curl -fsS "$BASE_URL/api/v1/health/live"
curl -fsS "$BASE_URL/api/v1/health/ready"
```

全部完成后才切换正式流量：

- 使用已有账号登录。
- 核对用户数量、余额、流水和成功/失败任务数量。
- 随机打开多张历史成图和参考图，确认对象存在且内容正确。
- 检查管理后台的依赖健康、outbox 积压和账务对账。
- 新建一张低成本测试任务，确认提交、生成、MinIO 落盘和结算完整。
- 记录恢复点时间、恢复开始时间和完成时间，得到实际 RPO 与 RTO。

## 3. 当前未覆盖的风险

- 备份脚本不做静态加密，`.env` 和图片快照依赖备份存储自身的磁盘加密与访问控制。
- 尚未在隔离环境完成正式恢复演练，RTO 没有实测数据。
- 尚未提供备份失败的外部告警。
- 单份备份存储仍是故障点，应另有异地或离线副本。

以上事项完成前，不应把 ROADMAP 中的 P0“备份与恢复演练”标记为关闭。
