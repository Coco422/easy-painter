# v0.18.0：MinIO 迁移到 RustFS

v0.18.0 的开发与生产 Compose 使用 RustFS 1.0.0，并固定官方镜像摘要。S3 API 和控制台仍使用 9000、9001 端口；开发端口覆盖仍为 `MINIO_API_PORT`、`MINIO_CONSOLE_PORT`。生产默认不向宿主机暴露这两个端口。

## 配置与初始化

- 为兼容现有 `.env`，保留 `MINIO_*` 配置名。`MINIO_ROOT_USER/PASSWORD` 映射到服务端的 `RUSTFS_ACCESS_KEY/SECRET_KEY`，`MINIO_ACCESS_KEY/SECRET_KEY` 是应用的 S3 凭证。首次安装时两组值保持一致；原有独立应用账号需要在 RustFS 重新建立并授权，不能假设账号会随图片复制。
- 新环境使用 `MINIO_ENDPOINT=rustfs:9000`。Compose 保留 `minio` DNS 别名兼容旧配置；自定义外部地址仍需自行调整。
- 后端保留 `minio` Python SDK、`MinioStorageService` 类名和健康接口的 `minio` 字段；管理界面显示 RustFS。业务继续使用标准 S3 上传、复制、下载与删除接口。
- `rustfs-permissions` 仅将新 `data/rustfs` 目录本身设为 UID/GID `10001:10001`。RustFS 通过 `/health/ready` 就绪后，`storage-init` 使用后端镜像创建两个 bucket 并移除匿名访问策略；初始化失败会阻止 API、worker、dispatcher 启动。
- 图片仍由 API 鉴权后返回。无需开放 bucket 匿名读取，无需数据库迁移，Flyway 版本仍为 V8。

## 已有部署的升级顺序

不要直接执行常规 `up -d --remove-orphans`：新 RustFS 数据目录初始为空，必须先迁移对象。不要把 `data/minio` 挂载或改名为 `data/rustfs`。以下过程保留旧目录，通过 S3 复制当前对象；bucket 名称、object key 和 Content-Type 必须保持一致。本项目未启用对象版本、服务端加密或复制策略；如果自行启用了这些能力，需要另行迁移历史版本、密钥及策略。

1. 在当前部署目录保存旧 `compose.yml` 和 `.env`，例如 `compose.pre-rustfs.yml`、`.env.pre-rustfs`，权限均设为 `600`。同时保存旧镜像，避免恢复依赖远程旧镜像的可用性。
2. 进入维护窗口，先停止 nginx/API 入口，等待现有任务完成、outbox 和队列排空，再停止 worker、dispatcher。确认无人通过控制台写入或删除对象。
3. 在备份环境使用 `EASY_PAINTER_STORAGE_ENGINE=minio` 运行备份脚本，验证数据库 SHA-256 和旧 `minio/` 快照。保留此完整恢复点。
4. 安装已发布的 v0.18.0 `compose.yml`，更新 `.env` 中 `IMAGE_TAG=v0.18.0`、`MINIO_ENDPOINT=rustfs:9000`；保留旧 bucket 名称和凭证，或同步配置新的应用凭证。确认版本镜像已发布后才进行实际部署。
5. 启动 RustFS、初始化 bucket，再按下文复制与校验。此阶段不要启动业务容器，也不要使用 `--remove-orphans`，旧 MinIO 仍是复制源。

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --wait rustfs
docker compose -f compose.yml run --rm --no-deps storage-init
```

### 通过 S3 复制

在运维主机准备已有的 MinIO Client `mc` 命令行工具（仅用于这次迁移，应用部署不再依赖 `minio/mc` 镜像）。为两个服务分别临时增加只监听回环地址的端口：

`migration-source.yml`：

```yaml
services:
  minio:
    ports:
      - "127.0.0.1:19000:9000"
```

`migration-target.yml`：

```yaml
services:
  rustfs:
    ports:
      - "127.0.0.1:29000:9000"
```

```bash
docker compose --env-file .env.pre-rustfs -f compose.pre-rustfs.yml -f migration-source.yml up -d minio
docker compose -f compose.yml -f migration-target.yml up -d --wait rustfs
```

在受控终端中设置 `SOURCE_ACCESS_KEY`、`SOURCE_SECRET_KEY`、`TARGET_ACCESS_KEY`、`TARGET_SECRET_KEY` 以及原有 `MINIO_BUCKET`、`MINIO_REFERENCE_BUCKET`，不要把真实值写入仓库或共享日志。`mc` 会把凭证存入自己的本地配置，应限制该目录权限。随后执行：

```bash
mc alias set painter-source http://127.0.0.1:19000 "$SOURCE_ACCESS_KEY" "$SOURCE_SECRET_KEY"
mc alias set painter-target http://127.0.0.1:29000 "$TARGET_ACCESS_KEY" "$TARGET_SECRET_KEY"

mc mirror --overwrite "painter-source/$MINIO_BUCKET" "painter-target/$MINIO_BUCKET"
mc mirror --overwrite "painter-source/$MINIO_REFERENCE_BUCKET" "painter-target/$MINIO_REFERENCE_BUCKET"

mc diff "painter-source/$MINIO_BUCKET" "painter-target/$MINIO_BUCKET"
mc diff "painter-source/$MINIO_REFERENCE_BUCKET" "painter-target/$MINIO_REFERENCE_BUCKET"
```

逐条确认命令成功后继续。复制可重复执行；不使用 `--remove`，不删除源对象。`mc diff` 用于核对缺失对象与大小差异，不能代替内容校验。再核对两侧对象数量、总大小，并抽样下载生成图、社区精选图、参考图比较 SHA-256 及 Content-Type；保留验证记录。自定义 IAM 用户、策略和历史对象版本不由以上命令复制。

### 切换与验收

1. 停止旧 MinIO，避免其服务名与新 Compose 的兼容 DNS 别名冲突。
2. 移除临时端口：仅使用正式 `compose.yml` 重建 RustFS，等待就绪。临时 override 文件不参与后续启动。
3. 使用应用实际凭证确认两个 bucket 可读写；需要独立应用账号时，先通过 RustFS 控制台建立账号和最小必要授权。
4. 执行 Flyway 和完整服务启动，验收通过后再退出维护窗口。

```bash
docker compose --env-file .env.pre-rustfs -f compose.pre-rustfs.yml stop minio
docker compose -f compose.yml up -d --force-recreate --wait rustfs
docker compose -f compose.yml run --rm --no-deps storage-init
docker compose -f compose.yml run --rm migrate
docker compose -f compose.yml up -d --remove-orphans
```

验收包含 `/api/v1/health/ready`、管理后台 RustFS 健康、历史成图/社区图/参考图读取、多参考图复制、一次生成及计费结算、删除队列。匿名直接访问 bucket/object 应失败。启用新版备份脚本的默认 RustFS 模式并检查新快照的 `storage_engine=rustfs` 与 `rustfs/` 目录。确认备份任务已更新，不能继续只备份旧 `data/minio`。

## 回滚

如果尚未恢复业务写入，停止新版业务与 RustFS，恢复保存的旧 Compose、`.env` 及上一正式版本镜像，使用原 `data/minio` 启动并验证。旧镜像必须搭配旧 Compose，不能仅改 `IMAGE_TAG` 让旧配置误读新存储。

如果已经在 RustFS 上产生新图片或数据库写入，直接切回旧目录会丢失新图片。应再次停写，选择协调迁移新增对象和对应数据库状态，或从升级前的 PostgreSQL + MinIO 完整快照一起恢复；后者会丢弃恢复点之后的业务变化。Redis 队列不从旧备份恢复。确认回滚策略前保留两份存储目录和完整快照。

参考：[RustFS 1.0.0](https://github.com/rustfs/rustfs/releases/tag/1.0.0)、[Docker 安装与目录权限](https://docs.rustfs.com/en/installation/container/docker)、[就绪检查](https://docs.rustfs.com/en/operations/status-check)。
