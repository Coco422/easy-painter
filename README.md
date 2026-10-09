# Easy Painter

可自部署的 AI 绘画平台，支持多模型生图、多参考图、批量生成、无限画布、作品画廊与积分管理。

前端使用 **Vue 3 + TypeScript + Vite**，后端使用 **FastAPI + Celery**，配套 PostgreSQL、Redis、RustFS 和 Flyway，通过 Docker Compose 部署。

## 功能

- **图片创作**：文生图、多参考图、批量生成、任务恢复与趣味等待动画；重复参考图按文件内容去重。
- **无限画布**：节点连线、分组、撤销重做、本地保存与项目导入导出；VIP 可开启云端同步。
- **作品管理**：生图历史、个人画廊、收藏与社区投稿审核。
- **账号与计费**：邮箱验证、用户组、积分预扣、成功结算与失败退款。
- **管理后台**：配置模型、上游渠道、用户、定价与通知，查看任务和系统状态。
- **自动发布**：正式版本 tag 触发镜像构建、GitHub Release 与生产 CD。

## 快速开始

需要 Python 3.12、uv、Node.js 22+ 和 Docker Compose。

```bash
git clone https://github.com/Coco422/easy-painter.git
cd easy-painter
cp .env.example .env
```

编辑 `.env`，配置上游 API、数据库、对象存储和认证密钥；开启邮箱注册或找回密码时，还需配置 SMTP。模型能力和价格由管理后台维护。

**本地开发**：在三个终端分别运行，保持依赖终端开启。

```bash
make deps      # 数据库、缓存、存储、迁移和任务服务
make backend   # API：http://localhost:8000
make frontend  # 前端：http://localhost:5173
```

**本地容器部署**：

```bash
make deploy
```

详细配置、首次服务器部署及历史版本升级见 [配置与部署指南](docs/setup-and-operations.md)。

## 测试

```bash
(cd backend && uv run pytest)
(cd frontend && npm run build)
(cd frontend && node --experimental-strip-types --test tests/*.test.mjs)
```

从仓库根目录执行；前端 build 包含类型检查。

## 发布

先更新 `CHANGELOG.md`，再同步并检查版本：

```bash
python3 scripts/version.py set vX.Y.Z
python3 scripts/version.py check vX.Y.Z
python3 scripts/version.py notes vX.Y.Z
```

将代码合入 `main` 后，创建并推送新的 `vX.Y.Z` tag。GitHub Actions 构建 backend、nginx 和 migrations 镜像，创建 Release；配置 `production` 环境后，CD 自动部署并检查服务就绪状态。普通 `main` push 只构建，不部署。

生产必须固定正式版本 tag。配置凭证、备份与失败恢复见 [自动部署指南](docs/continuous-deployment.md)。

## 使用与文档

普通账号生成图和参考图默认保留 **48 小时**，VIP 按用户组策略保留。画布默认保存在当前浏览器，清理网站数据会移除本地项目，请定期导出备份。社区公开图片及提示词需要用户同意并通过审核。

- [配置与部署](docs/setup-and-operations.md) · [开发测试数据](docs/development-data.md)
- [备份与灾难恢复](docs/backup-and-disaster-recovery.md) · [MinIO → RustFS 迁移](docs/minio-to-rustfs.md)
- [无限画布使用说明](docs/v0.20.0-release.md) · [作品管理与保留期升级](docs/v0.19.0-release.md)
- [更新日志](CHANGELOG.md) · [路线图](ROADMAP.md) · [开发约定](AGENTS.md)

上游与 SMTP 凭证仅保存在后端环境配置中，请勿提交真实 `.env`。图片通过后端鉴权访问，对象存储不开放匿名直连。开发环境可通过后端 `/docs` 查看 API 文档，生产环境默认关闭。

## 致谢

无限画布参考 [basketikun/infinite-canvas](https://github.com/basketikun/infinite-canvas)（MIT）。参考范围、版本与许可证见 [第三方声明](THIRD_PARTY_NOTICES.md)。
