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
├── backend
├── deploy/nginx
├── frontend
├── docker-compose.yml
└── .env.example
```

## 本地开发

### 1. 准备环境变量

```bash
cp .env.example .env
```

把 `.env` 中的 `UPSTREAM_BASE_URL` 和 `UPSTREAM_API_KEY` 替换成你的私有上游配置，不要把真实值写进前端或提交到仓库。

### 2. 启动基础服务

```bash
docker compose up -d postgres redis minio minio-init
```

### 3. 启动后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 启动 Celery Worker

```bash
cd backend
uv run celery -A app.worker.celery_app worker --loglevel=INFO
```

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

开发环境下前端会把 `/api` 转发到 `http://127.0.0.1:8000`，把 `/media` 转发到 `http://127.0.0.1:8080`。

## 一键部署

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

部署完成后：

- 首页由 `nginx` 提供静态文件
- `/api/...` 反代到 `api`
- `/media/...` 反代到 MinIO 公共 bucket

## M2 开发机与 amd64 服务器

这个项目的 Dockerfile 和依赖都兼容多架构，不需要在 `docker-compose.yml` 里强行写死 `platform`。

- 如果你在 `linux/amd64` 服务器上直接部署：最简单，直接在服务器执行 `docker compose build && docker compose up -d`。
- 如果你在 M2 本机先构建镜像再推送到 amd64 服务器：请使用 `docker buildx` 指定 `linux/amd64`。

示例：

```bash
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t your-registry/easy-painter-api:latest --push .
docker buildx build --platform linux/amd64 -f deploy/nginx/Dockerfile -t your-registry/easy-painter-nginx:latest --push .
```

`worker` 与 `api` 复用同一个后端镜像，所以后端只需要构建一次。

## 对外接口

- `GET /api/v1/meta/public`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/gallery`
- `GET /api/v1/healthz`

## 安全说明

- 上游地址和密钥只允许出现在 `.env` 与后端容器环境变量。
- 前端打包产物不包含任何上游地址。
- API 返回值、错误提示和日志都使用通用文案，不回显上游主机名或密钥。
