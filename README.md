# Easy Painter

一个基于 `FastAPI + Celery + Vue` 的单页文生图系统，前端只访问本站 `/api/...`，上游图像生成地址仅保存在后端容器环境变量中，不会出现在浏览器请求、静态资源或公开接口里。

## 技术栈

- `frontend/`: Vue 3 + Vite + TypeScript 单页应用
- `backend/`: FastAPI + Celery + SQLAlchemy + Redis + RustFS
- `backend/db/`: Flyway forward-only SQL migrations 与独立 migrations 镜像
- `uv`: Python 依赖管理
- `docker-compose.yml`: `migrate`、`api`、`worker`、`dispatcher`、`nginx`、`redis`、`postgres`、`rustfs`、`storage-init`

## 目录结构

```text
.
├── VERSION
├── CHANGELOG.md
├── ROADMAP.md
├── backend
├── docs/backup-and-disaster-recovery.md
├── deploy/nginx
├── frontend
├── scripts/backup-production.sh
├── scripts/version.py
├── docker-compose.yml
└── .env.example
```

## 无限画布

v0.20.0 保留 `/create` 普通创作台，新增「无限画布」入口。登录后可创建多个画布，把图片、提示词和生成配置组织为节点，支持连线、分组、框选、平移缩放、撤销重做以及生成结果回填。

画布和素材默认保存在当前浏览器，按账号隔离，可导入、导出包含图片的完整项目。清理网站数据会移除本地内容，请定期导出备份。AI 生成仍使用现有后端和计费流程。

VIP 用户组可按画布开启云端同步：先本地保存，再同步变化与新增素材，支持跨设备恢复和版本冲突检查。普通账号仍可使用本地画布；VIP 降组后可恢复、导出或删除已有云端项目。首次升级需执行 Flyway V10，具体限制与升级步骤见 [v0.20.0 使用与升级说明](docs/v0.20.0-release.md)。

## 作品管理与图片保留期

v0.19.0 将生图历史、个人画廊、收藏和社区投稿分开：历史保存全部任务与过期后的文字记录；个人画廊由用户主动加入作品；收藏仅保存引用。社区投稿需要开启个人中心公开总开关、确认公开图片与提示词，并由管理员审核通过。已收录内容使用独立长期副本，原作到期或撤回不影响社区版本。

非 VIP 生成图与参考图默认保留 48 小时，卡片和详情显示实际截止时间；VIP 保留原用户组策略。**升级时仍有效的非 VIP 存量图片将统一改为迁移后 48 小时**，不会恢复已过期或删除中的图片。升级涉及 V9、缩略图补齐和 API/worker/dispatcher/前端同步，操作前阅读 [v0.19.0 升级说明与验收](docs/v0.19.0-release.md)。

## 版本与发布

项目使用标准语义化版本 `vX.Y.Z`。根目录 [`VERSION`](VERSION) 是当前版本号的唯一来源，[`CHANGELOG.md`](CHANGELOG.md) 是发布说明的唯一来源；维护者在发布时用中文人工概括两个版本之间的用户可感知变化。产品方向记录在 [`ROADMAP.md`](ROADMAP.md)。

```bash
# 同步 VERSION、前后端 manifest 和 lockfile
python3 scripts/version.py set vX.Y.Z

# 检查版本文件、changelog 和 manifest 是否一致
python3 scripts/version.py check vX.Y.Z

# 预览该版本将写入 GitHub Release 的说明
python3 scripts/version.py notes vX.Y.Z
```

前端构建时会把当前版本和 changelog 编译进静态资源。所有访客都可以从 Header 打开版本中心；弹窗打开后只读查询官方仓库最新正式 GitHub Release，发现新版时提供 Release 链接，但不会自动下载或升级。正式发布时推送 `vX.Y.Z` tag，GitHub Actions 会先执行一致性检查，再用对应 changelog 章节创建 Release。

## 本地开发

### v0.18.0 对象存储升级

对象存储已替换为 RustFS 1.0.0，使用独立的 `data/rustfs` 目录；旧 `MINIO_*` 配置名与 S3 SDK 保留兼容。已有部署必须先按 [MinIO → RustFS 迁移指南](docs/minio-to-rustfs.md) 复制并校验两个私有 bucket，再启动新版业务。不能直接套用常规升级命令或复用 `data/minio`。备份脚本默认备份 RustFS，旧环境升级前备份需设置 `EASY_PAINTER_STORAGE_ENGINE=minio`。

### 1. 准备环境变量

```bash
cp .env.example .env
```

将 `.env` 中的 `UPSTREAM_BASE_URL` 和 `UPSTREAM_API_KEY` 配置为实际使用的私有上游地址与密钥，不要把真实值写进前端或提交到仓库。
模型下拉列表、参考图能力、单次参考图上限和尺寸限制以管理后台的模型配置为准。`PUBLIC_MODELS_JSON` 用于首次初始化与数据库读取失败时的回退；修改它不会覆盖已经入库的模型。
部分绘图模型生成时间可能达到 30 到 600 秒，生产环境的 `UPSTREAM_TIMEOUT_SECONDS` 应保持在 700 左右。
提示词输入不在前端截断，后端通过 `PROMPT_MAX_LENGTH` 做硬限制，默认 4000 字符。
`GENERATION_JOB_STALE_SECONDS` 与 `GENERATION_QUEUE_STALE_SECONDS` 分别控制执行中、排队中任务的 watchdog 超时。Dispatcher 每 2 秒投递 transactional outbox，并周期执行卡单退款和账务对账；这些间隔可通过 `OUTBOX_*`、`WATCHDOG_INTERVAL_SECONDS` 与 `RECONCILIATION_INTERVAL_SECONDS` 调整。

### 多参考图与数量配置

在「管理后台 → 模型管理 → 编辑」中设置 **单次参考图上限**（`max_reference_images`），默认 5，可调整为 2、12 等正整数。保存后新任务按新配置校验，无需重启；已打开的创作页刷新后同步显示。已入队任务使用提交时的参考图快照，不受之后限额变更影响。

- 创作台支持多选上传、拖放、粘贴和从历史中追加选择，按显示的“参考图 1、2…”顺序提交；超过当前模型上限时阻止生成，不自动丢弃已选图片。
- 模型的“支持参考图”开关仍独立生效。新安装的 GPT Image B/C 默认开启；已有数据库中的开关和名称保留，如 C 以前关闭了参考图，需要在模型管理中开启。
- 用户组的“参考图上限”是**图库保存配额**，与模型单次输入上限独立。若要同时选择 5 或 12 张，用户组保存配额也需至少为对应数量；达到配额时仍按原流程确认后淘汰最旧图片，被淘汰的已选图会从创作框移除。
- `POST /api/v1/jobs` 接受有序 `reference_image_ids` 数组；旧 `reference_image_id` 和单图 multipart 继续兼容。不能同时提交新旧 ID 字段，也不能重复引用同一张图片。每个 ID 均检查归属、有效期和可用状态。
- GPT Image B/C 使用 `/images/edits` 的重复 `image` 文件字段；豆包多图使用 `image[]`。每张图复制到独立任务路径，失败回滚会清理已复制对象，终态清理覆盖全部参考图。
- 升级包含 Flyway `V8__multiple_job_reference_images.sql`，增加模型数量限制和任务多图快照列。按正常流程先迁移，再同步升级 API、worker 与前端。此功能不代表已验证上游的真实最大输入数量；生产上游实测需另行进行。

首次初始化也可以在 `PUBLIC_MODELS_JSON` 的模型条目中指定 `"max_reference_images": 12`。

### SMTP、注册、忘记密码与邮箱绑定

注册账号需要先验证邮箱；登录支持用户名或邮箱；忘记密码通过邮箱验证码直接设置新密码，不需要输入原密码。历史账号如果还没有邮箱，可以登录后在个人中心发送验证码并绑定邮箱；已绑定邮箱不能自行更换，需要由管理员处理。个人中心不提供修改密码入口，管理员仍可在后台直接重置任意用户密码。

邮件使用标准 SMTP 发送，至少需要配置：

```dotenv
REGISTRATION_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=no-reply@example.com
SMTP_PASSWORD=replace-with-smtp-password-or-app-token
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_FROM_NAME=一丝绘画站
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

- 端口 `587` 通常使用 STARTTLS：`SMTP_USE_TLS=true`、`SMTP_USE_SSL=false`。
- 端口 `465` 通常使用 SSL：`SMTP_USE_TLS=false`、`SMTP_USE_SSL=true`。
- Gmail、QQ 邮箱等服务通常要求使用“应用专用密码/授权码”，不要填写网页登录密码。
- 验证码只以 HMAC 摘要形式暂存在 Redis，默认 10 分钟失效；连续输错 5 次后立即作废。
- 发送接口使用 Redis 原子冷却，默认同一邮箱 60 秒内只允许发送一次；同时按邮箱、来源 IP 和已登录用户限制 10 分钟与 24 小时发送量，超限返回 `429` 和 `Retry-After`。
- 找回密码对未注册邮箱返回统一成功文案且不发送邮件，避免泄露账号是否存在；绑定邮箱验证码额外绑定当前用户 ID，不能跨账号复用。
- SMTP 发送失败会删除刚生成的验证码并释放本次冷却，不会留下可验证但未送达的验证码。
- `DEFAULT_EMAIL` 只在首次创建默认用户时使用；已有无邮箱用户可自行验证绑定，也可由管理员在用户管理中补录邮箱。
- `JWT_SECRET_KEY` 请使用至少 32 字节的随机值；修改后现有登录令牌会失效，需要重新登录。

### 全局生成统计

前台普通页面在顶部导航下方展示生成统计，每 5 秒轮播“今日已生成图片 N 张”和“系统运行至今已生成 N 张”，每 60 秒刷新数据。点击可手动切换，悬停或键盘聚焦时暂停轮播。无限画布页隐藏统计与横幅，保留完整编辑空间。

- `GET /api/v1/stats/public` 无需登录，返回 `today_images`、`total_images`，仅公开汇总数量；响应可缓存 30 秒。
- 全站每个成功任务计为一张图片，包含私有图片与匿名任务；排队中、生成中和失败任务不计入。
- “今日”按北京时间（UTC+8）零点至次日零点、以 `finished_at` 完成时间统计。历史成功任务缺少完成时间时只计入累计数量。
- 删除图片、媒体过期或清理存储不会扣减历史生成数量；统计直接聚合现有任务记录，无需新增迁移。
- 请求失败时隐藏统计，下次刷新重试；首次加载时不显示虚假的零值。

### 系统横幅通知

管理后台的“通知管理”支持同时维护多条横幅，可设置普通、提醒或重要级别，并按以下受众投放：

- `all`：所有访客，包括未登录游客。
- `authenticated`：所有已登录用户。
- `unbound_email`：仅已登录且尚未绑定邮箱的用户；前端会提供“去绑定邮箱”快捷入口。

通知正文按纯文本渲染。后台提供“填入邮箱提醒”模板，但不会在启动时自动播种通知，避免管理员删除后又被自动重建。

### 2. 准备本地工具

```bash
uv --version
node --version
docker --version
```

本地开发环境需要具备：

- Python 3.12
- `uv`
- Node.js / npm
- Docker / Docker Compose

### 数据库迁移与账务可靠性

数据库结构只由 Flyway 管理，API 启动时不会执行 `create_all` 或临时 `ALTER TABLE`。空库会顺序执行全部迁移；已有但没有 Flyway history 的旧库会以 v1 baseline 标记，再升级到账务、幂等与 outbox schema。

```bash
# 显式执行迁移；失败时 API、Worker 和 Dispatcher 不应启动
make migrate
```

- `generation_jobs`、预扣、负流水与 outbox 在同一数据库事务内创建。
- 新版前端为每张生成任务发送稳定 `Idempotency-Key`；网络重试不会重复扣费。
- 任务只有成功交付图片才结算，入队超时、上游失败、存储失败或执行超时均全额退款。
- `credit_transactions` 在 PostgreSQL 中为 append-only；Dispatcher 会以不可变流水重算并修复余额缓存。
- Flyway 迁移仅向前执行。生产升级前应同时备份 PostgreSQL 与 RustFS，回滚依赖备份恢复。
- 生产备份内容、快照校验和新环境恢复步骤见 [`docs/backup-and-disaster-recovery.md`](docs/backup-and-disaster-recovery.md)。

### 3. 启动依赖服务和 Celery

```bash
make deps
```

这个命令会以前台方式启动 `postgres`、`redis`、`rustfs`、`storage-init`、`migrate`、`worker` 和 `dispatcher`，便于调试日志；退出命令时会自动把这些容器关掉。迁移失败时 Worker 与 Dispatcher 不会继续启动。

### 4. 启动后端 API

```bash
make backend
```

### 5. 启动前端

```bash
make frontend
```

开发环境下：

- 前端会把 `/api` 转发到 `http://127.0.0.1:8000`
- `/media` 仍然走 `http://127.0.0.1:8080`
- `make backend` 会自动把数据库、Redis、RustFS 连接改为宿主机端口，配合 `make deps` 启动的容器使用

## 本地镜像部署

```bash
cp .env.example .env
make deploy
```

部署完成后：

- 首页由 `nginx` 提供静态文件
- `/api/...` 反代到 `api`
- 图片通过 `/api/...` 鉴权后读取 RustFS 私有 bucket，`/media/...` 不开放直连

## 服务器部署（GHCR）

`main` 分支更新相关文件或推送 `vX.Y.Z` 正式版本标签时，GitHub Actions 会构建三个 `linux/amd64` 镜像并推送到 GHCR。`main` 和 `sha-*` 仅用于构建验证与问题定位；每次生产部署必须先创建新的语义化版本，并固定使用对应的 `vX.Y.Z` 镜像标签：

- `ghcr.io/coco422/easy-painter-backend`
- `ghcr.io/coco422/easy-painter-nginx`
- `ghcr.io/coco422/easy-painter-migrations`

服务器不需要 Git 仓库、Node.js 或 Python 构建环境，只需保留：

- `.env`
- `compose.yml`（使用仓库中的 `deploy/compose.yml`）
- `data/postgres`、`data/redis`、`data/rustfs` 持久化目录

首次部署：

```bash
mkdir -p ~/easy-painter
cd ~/easy-painter
curl -fsSLo compose.yml https://raw.githubusercontent.com/Coco422/easy-painter/main/deploy/compose.yml
curl -fsSLo .env https://raw.githubusercontent.com/Coco422/easy-painter/main/.env.example
```

启动前必须编辑 `.env`，替换示例凭证、上游配置和管理员密钥；不要直接使用模板中的默认值部署到公网。配置完成后启动服务：

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --remove-orphans
```

后续更新必须先按“版本与发布”章节完成版本号、changelog、测试、提交和 tag，再等待三个版本镜像构建成功。服务器只部署新的正式版本标签：

```bash
cd ~/easy-painter
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=vX.Y.Z/' .env
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --remove-orphans
```

`IMAGE_TAG` 模板默认使用 `main`，只适合本地或临时验证。生产环境必须固定为新发布的 `vX.Y.Z`；回滚时固定为上一个已经验证的正式版本：

```dotenv
IMAGE_TAG=vX.Y.Z
```

```bash
IMAGE_TAG=v<上一正式版本> docker compose -f compose.yml pull
IMAGE_TAG=v<上一正式版本> docker compose -f compose.yml up -d --remove-orphans
```

GHCR 包必须允许服务器拉取：公开包可匿名拉取；私有包需先执行 `docker login ghcr.io`。只有在新镜像成功启动并通过健康检查后，才能删除服务器上的源码，且不得删除 `.env`、`compose.yml` 和 `data/`。

## Apple Silicon 与 amd64 镜像

项目的 Dockerfile 和依赖兼容多架构，通常不需要在 `docker-compose.yml` 中写死 `platform`。

- 使用 Apple M 系列芯片构建并将镜像部署到 amd64 环境时，需要通过 `docker buildx` 指定 `--platform linux/amd64` 进行交叉构建。

示例：

```bash
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t your-registry/easy-painter-api:latest --push .
docker buildx build --platform linux/amd64 -f deploy/nginx/Dockerfile -t your-registry/easy-painter-nginx:latest --push .
```

`worker` 与 `api` 复用同一个后端镜像，所以后端只需要构建一次。

## 对外接口

- `GET /api/v1/meta/public`
- `GET /api/v1/canvas/capabilities`（云端画布权限与容量）
- `GET/POST /api/v1/canvas/projects`（列出 / 创建云端画布）
- `GET/PUT/DELETE /api/v1/canvas/projects/{id}`（读取 / 版本检查保存 / 删除）
- `GET/PUT /api/v1/canvas/projects/{id}/assets/{digest}`（私有素材读取 / 去重上传）
- `POST /api/v1/auth/email-codes`（发送注册或重置密码验证码）
- `POST /api/v1/auth/register`（验证邮箱并注册）
- `POST /api/v1/auth/login`（用户名或邮箱登录）
- `POST /api/v1/auth/password/reset`（邮箱验证码重置密码）
- `GET /api/v1/announcements`（按当前登录与邮箱状态读取启用的横幅通知）
- `POST /api/v1/users/me/email/code`（登录后发送绑定邮箱验证码）
- `PUT /api/v1/users/me/email`（验证并绑定邮箱）
- `POST /api/v1/jobs`
- `POST /api/v1/reference-images`（登录后预上传参考图）
- `GET /api/v1/reference-images`（登录后读取参考图历史）
- `GET /api/v1/reference-images/{id}/file`（登录后读取私有参考图）
- `DELETE /api/v1/reference-images/{id}`（登录后删除参考图）
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/history`（全部生成记录，分页、状态、提示词与日期筛选）
- `GET /api/v1/portfolios/{username}`（个人作品集）
- `PUT/DELETE /api/v1/jobs/{job_id}/gallery`（加入或移出画廊）
- `GET /api/v1/favorites`（全部、可用或失效收藏）
- `PUT/DELETE /api/v1/favorites/{job|inspiration}/{id}`（引用收藏）
- `POST/DELETE /api/v1/jobs/{job_id}/community-submission`（主动投稿与撤回）
- `GET /api/v1/admin/community-submissions`、`PUT /api/v1/admin/community-submissions/{job_id}`（审核）
- `GET/HEAD /api/v1/artworks/{job|inspiration}/{id}/file?variant=thumbnail|original`（鉴权图片）
- `GET /api/v1/gallery`（旧版兼容接口）
- `GET /api/v1/healthz`

Admin 通知接口保持独立管理员令牌认证：

- `GET /api/v1/admin/announcements`
- `POST /api/v1/admin/announcements`
- `PUT /api/v1/admin/announcements/{id}`
- `DELETE /api/v1/admin/announcements/{id}`
- `GET /api/v1/admin/overview?window=24h`
- `GET /api/v1/admin/health`

## 安全说明

- 上游地址和密钥只允许出现在 `.env` 与后端容器环境变量。
- 前端打包产物不包含任何上游地址。
- API 返回值、错误提示和日志都使用通用文案，不回显上游主机名或密钥。
- SMTP 密码只允许保存在 `.env` 与后端容器环境变量中，不会通过公开接口返回。
- 生产环境应根据邮件服务商配额调整 `EMAIL_CODE_*` 限额；如果站点暴露在高风险公网环境，建议在反向代理层再叠加全局限流或验证码挑战。

## 致谢

感谢 [basketikun](https://github.com/basketikun) 开源的 [infinite-canvas（无限画布）](https://github.com/basketikun/infinite-canvas)。Easy Painter 的无限画布以该项目为主要参考，重点借鉴其节点式创作交互、画布编排、连续生成流程以及浏览器本地保存画布与素材的设计，并适配本项目的 Vue 3、用户组、生成与计费体系。

该参考项目采用 [MIT License](https://github.com/basketikun/infinite-canvas/blob/main/LICENSE)，参考版本、适配范围及完整版权与许可证文本见 [第三方声明](THIRD_PARTY_NOTICES.md)。
