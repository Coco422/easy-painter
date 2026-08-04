# Easy Painter

一个基于 `FastAPI + Celery + Vue` 的单页文生图系统，前端只访问本站 `/api/...`，上游图像生成地址仅保存在后端容器环境变量中，不会出现在浏览器请求、静态资源或公开接口里。

## 技术栈

- `frontend/`: Vue 3 + Vite + TypeScript 单页应用
- `backend/`: FastAPI + Celery + SQLAlchemy + Redis + MinIO
- `uv`: Python 依赖管理
- `docker-compose.yml`: `nginx`、`api`、`worker`、`redis`、`postgres`、`minio`、`minio-init`

## 目录结构

```text
.
├── VERSION
├── CHANGELOG.md
├── ROADMAP.md
├── backend
├── deploy/nginx
├── frontend
├── scripts/version.py
├── docker-compose.yml
└── .env.example
```

## 版本与发布

项目使用标准语义化版本 `vX.Y.Z`。根目录 [`VERSION`](VERSION) 是当前版本号的唯一来源，[`CHANGELOG.md`](CHANGELOG.md) 是发布说明的唯一来源；维护者在发布时用中文人工概括两个版本之间的用户可感知变化。产品方向记录在 [`ROADMAP.md`](ROADMAP.md)。

```bash
# 同步 VERSION、前后端 manifest 和 lockfile
python3 scripts/version.py set v0.12.0

# 检查版本文件、changelog 和 manifest 是否一致
python3 scripts/version.py check v0.12.0

# 预览该版本将写入 GitHub Release 的说明
python3 scripts/version.py notes v0.12.0
```

前端构建时会把当前版本和 changelog 编译进静态资源。所有访客都可以从 Header 打开版本中心；弹窗打开后只读查询官方仓库最新正式 GitHub Release，发现新版时提供 Release 链接，但不会自动下载或升级。正式发布时推送 `vX.Y.Z` tag，GitHub Actions 会先执行一致性检查，再用对应 changelog 章节创建 Release。

## 本地开发

### 1. 准备环境变量

```bash
cp .env.example .env
```

把 `.env` 中的 `UPSTREAM_BASE_URL` 和 `UPSTREAM_API_KEY` 替换成你的私有上游配置，不要把真实值写进前端或提交到仓库。
模型下拉列表、参考图能力和尺寸限制由 `PUBLIC_MODELS_JSON` 控制；如果生产环境要开放新模型，需要同步更新服务器上的 `.env`。
部分绘图模型生成时间可能达到 30 到 600 秒，生产环境的 `UPSTREAM_TIMEOUT_SECONDS` 应保持在 700 左右。
提示词输入不在前端截断，后端通过 `PROMPT_MAX_LENGTH` 做硬限制，默认 4000 字符。
`GENERATION_JOB_STALE_SECONDS` 用于把服务重启或 worker 中断后遗留的任务收敛为失败，默认 2700 秒。

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

需要本机具备：

- Python 3.12
- `uv`
- Node.js / npm
- Docker / Docker Compose

### 3. 启动依赖服务和 Celery

```bash
make deps
```

这个命令会以前台方式启动 `postgres`、`redis`、`minio`、`minio-init`、`worker`，便于调试日志；退出命令时会自动把这些容器关掉。

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
- `make backend` 会自动把数据库、Redis、MinIO 连接改成本机端口，配合 `make deps` 启动的容器使用

## 本地镜像部署

```bash
cp .env.example .env
make deploy
```

部署完成后：

- 首页由 `nginx` 提供静态文件
- `/api/...` 反代到 `api`
- `/media/...` 反代到 MinIO 公共 bucket

## 服务器部署（GHCR）

`main` 分支更新前后端或 Nginx 文件时，GitHub Actions 会构建两个 `linux/amd64` 镜像并推送到 GHCR：

- `ghcr.io/coco422/easy-painter-backend`
- `ghcr.io/coco422/easy-painter-nginx`

服务器不需要 Git 仓库、Node.js 或 Python 构建环境，只需保留：

- `.env`
- `compose.yml`（使用仓库中的 `deploy/compose.yml`）
- `data/postgres`、`data/redis`、`data/minio` 持久化目录

首次部署：

```bash
mkdir -p ~/easy-painter
cd ~/easy-painter
curl -fsSLo compose.yml https://raw.githubusercontent.com/Coco422/easy-painter/main/deploy/compose.yml
cp /path/to/existing/.env .env
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --remove-orphans
```

后续更新：

```bash
cd ~/easy-painter
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --remove-orphans
```

默认拉取 `main` 标签。生产部署也可以用不可变提交标签，便于精确回滚：

```bash
IMAGE_TAG=sha-<完整提交 SHA> docker compose -f compose.yml pull
IMAGE_TAG=sha-<完整提交 SHA> docker compose -f compose.yml up -d --remove-orphans
```

GHCR 包必须允许服务器拉取：公开包可匿名拉取；私有包需先执行 `docker login ghcr.io`。只有在新镜像成功启动并通过健康检查后，才能删除服务器上的源码，且不得删除 `.env`、`compose.yml` 和 `data/`。

## M2 开发机与 amd64 镜像

这个项目的 Dockerfile 和依赖都兼容多架构，不需要在 `docker-compose.yml` 里强行写死 `platform`。

- 如果你在 M2 本机先构建镜像再推送到 amd64 服务器：请使用 `docker buildx` 指定 `linux/amd64`。

示例：

```bash
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t your-registry/easy-painter-api:latest --push .
docker buildx build --platform linux/amd64 -f deploy/nginx/Dockerfile -t your-registry/easy-painter-nginx:latest --push .
```

`worker` 与 `api` 复用同一个后端镜像，所以后端只需要构建一次。

## 对外接口

- `GET /api/v1/meta/public`
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
- `GET /api/v1/gallery`
- `GET /api/v1/healthz`

Admin 通知接口保持独立管理员令牌认证：

- `GET /api/v1/admin/announcements`
- `POST /api/v1/admin/announcements`
- `PUT /api/v1/admin/announcements/{id}`
- `DELETE /api/v1/admin/announcements/{id}`

## 安全说明

- 上游地址和密钥只允许出现在 `.env` 与后端容器环境变量。
- 前端打包产物不包含任何上游地址。
- API 返回值、错误提示和日志都使用通用文案，不回显上游主机名或密钥。
- SMTP 密码只允许保存在 `.env` 与后端容器环境变量中，不会通过公开接口返回。
- 生产环境应根据邮件服务商配额调整 `EMAIL_CODE_*` 限额；如果站点暴露在高风险公网环境，建议在反向代理层再叠加全局限流或验证码挑战。
