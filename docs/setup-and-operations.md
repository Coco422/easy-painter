# 配置与部署指南

本文保留环境配置、本地运行与既有部署升级的详细说明。项目简介与快速启动见 [README](../README.md)，自动部署见 [CD 指南](continuous-deployment.md)。

## 本地开发

### 前端同事快速搭建测试环境

已有 [开发测试数据包操作手册](development-data.md) 与 `scripts/import-development-data.py`。同事自行准备本地服务、数据库完成数据包要求的迁移后，可导入测试账号、图片、账务及画廊/收藏/社区/过期样例；使用真实 API，无需生产备份或生产 `.env`。数据包不提供镜像、不启动服务，真实生图需另行配置独立测试渠道。

### v0.18.0 对象存储升级

对象存储已替换为 RustFS 1.0.0，使用独立的 `data/rustfs` 目录；旧 `MINIO_*` 配置名与 S3 SDK 保留兼容。已有部署必须先按 [MinIO → RustFS 迁移指南](minio-to-rustfs.md) 复制并校验两个私有 bucket，再启动新版业务。不能直接套用常规升级命令或复用 `data/minio`。备份脚本默认备份 RustFS，旧环境升级前备份需设置 `EASY_PAINTER_STORAGE_ENGINE=minio`。

### 1. 准备环境变量

```bash
cp .env.example .env
```

将 `.env` 中的 `UPSTREAM_BASE_URL` 和 `UPSTREAM_API_KEY` 配置为实际使用的私有上游地址与密钥，不要把真实值写进前端或提交到仓库。
模型下拉列表、参考图能力、单次参考图上限和尺寸限制以管理后台的模型配置为准。`PUBLIC_MODELS_JSON` 用于首次初始化与数据库读取失败时的回退；修改它不会覆盖已经入库的模型。 `upstream_model_id` 可在公共模型 ID 与主 chatgpt2api 实际模型名不同的时候使用。若要将现有数据库收敛到唯一公共模型并禁用旧模型，设置 `SYNC_PUBLIC_MODELS_FROM_ENV=true` 后重启 API/worker；该操作只禁用，不删除历史记录。

模型可选配置 `credit_cost_by_size`，按档设置基础价格，例如 `{"1k":5,"2k":8,"4k":12}`；`auto` 按 1K 档计费。具体尺寸按长边归档：不超过 1792px 为 1K，1793–2560px 为 2K，超过 2560px 为 4K。管理后台也可直接编辑此映射。创建任务时由服务端按请求尺寸选价，再应用用户组倍率并将价格快照写入账务；未配置档位的旧模型继续使用 `credit_cost`。
OpenAI GPT Image 2 的尺寸校验遵循官方上限：宽高必须是 16 的倍数，最长边不超过 3840px，长短边比例不超过 3:1，总像素在 655,360–8,294,400 之间；高于 2560×1440 的尺寸属于 experimental。前台只展示模型实际配置并且符合上述上限的尺寸。
部分绘图模型生成时间可能达到 30 到 600 秒，生产环境的 `UPSTREAM_TIMEOUT_SECONDS` 应保持在 700 左右。

需要同时接入多个 OpenAI 兼容渠道时，可在 `.env` 设置 `ADDITIONAL_UPSTREAMS_JSON`。默认只新增不存在的渠道和模型，不覆盖现有数据库配置；设置 `SYNC_PUBLIC_MODELS_FROM_ENV=true` 后会更新环境中配置的模型并停用未列出的模型，但不会删除历史记录。公共模型 ID 在数据库中全局唯一。备用映射可复用公共模型 ID，并设置 `fallback_for` 指向该模型，这样只保留一个前台选项。`route_for_sizes` 可配置 `1k`、`2k`、`4k` 尺寸路由；4K 请求只会调用标记了 `route_for_sizes:["4k"]` 的已验证渠道，缺少该渠道时直接失败并退款，不会静默降级到普通渠道。两个渠道使用同一 `base_url` 时必须使用不同的 `name` 和各自的 API Key。渠道凭证仅放在私有 `.env`，不能提交。渠道返回 `/v1/models` 不代表每个模型都兼容本站调用的 `/images/generations` 和 `/images/edits`，需要分别实测生成和参考图编辑；渠道价格也不自动换算为本站丝数。

示例：

```dotenv
ADDITIONAL_UPSTREAMS_JSON=[{"name":"ggwk1（1K/2K）","base_url":"https://www.ggwk1.online/v1","api_key":"replace-with-private-1k-key","timeout_seconds":700,"models":[{"id":"gpt-image-2","label":"备用模型","upstream_model_id":"gpt-image-2","fallback_for":"gpt-image-2","enabled":true,"supports_reference_image":true,"max_reference_images":1,"supported_sizes":[],"credit_cost":5,"credit_cost_by_size":{"1k":5,"2k":8},"route_for_sizes":["1k","2k"]}]},{"name":"ggwk1（4K专用）","base_url":"https://www.ggwk1.online/v1","api_key":"replace-with-private-4k-key","timeout_seconds":700,"models":[{"id":"gpt-image-2","label":"4K 专用路由","upstream_model_id":"gpt-image-2","fallback_for":"gpt-image-2","enabled":true,"supports_reference_image":true,"max_reference_images":1,"supported_sizes":["3840x2160","2160x3840"],"credit_cost":12,"route_for_sizes":["4k"]}]}]
```

示例价格是本站按请求尺寸收取的丝数，与渠道自身定价分开核算。备用映射不会创建重复的公共模型；独立模型 ID 被其他渠道占用时会保留原配置并跳过冲突项，后台可查看日志。主渠道连接失败或明确返回失败响应时才立即切换备用；读取超时或成功响应解析失败不立即切换，以减少结果不明时重复调用的风险。参考图数量超过备用配置上限时会跳过该备用；示例只启用已验证的单参考图备用能力。
提示词输入不在前端截断，后端通过 `PROMPT_MAX_LENGTH` 做硬限制，默认 4000 字符。
同一账号重复上传字节内容一致的参考图会复用仍有效的记录，不重复占用存储和图库配额，不延长有效期。
`GENERATION_JOB_STALE_SECONDS` 与 `GENERATION_QUEUE_STALE_SECONDS` 分别控制执行中、排队中任务的 watchdog 超时。Dispatcher 每 2 秒投递 transactional outbox，并周期执行卡单退款和账务对账；这些间隔可通过 `OUTBOX_*`、`WATCHDOG_INTERVAL_SECONDS` 与 `RECONCILIATION_INTERVAL_SECONDS` 调整。

### 生成配额与攻击防护

全站没有每日消费配额或每分钟生成次数配额，批量生成支持自定义正整数张数。`GENERATION_ABUSE_BURST_LIMIT=60` 仅控制同一账号一秒内的新生成请求洪峰，网页、普通 API、画布和 MCP 共用同一个 Redis 计数器；超限不扣费，返回 `429`，网页 API 提供 `Retry-After: 1`。旧的 `GENERATE_RATE_LIMIT_COUNT` / `GENERATE_RATE_LIMIT_WINDOW_SECONDS` 已不再使用，旧环境值不会恢复分钟配额；可从私有配置中移除。生成响应已移除 `rate_limit_remaining`。

正常批量通过前端有界队列提交；登录、验证码、OAuth 的防暴力破解/滥用及请求体大小限制继续保留。此账号级防刷不替代 CDN 的 IP/连接级攻击防护，不应为取消业务配额而关闭边缘防护。

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

注册只需邮箱、验证码和密码，系统自动生成唯一内部用户名与默认显示名称，避免邮箱出现在公开画廊地址中。以邮箱登录为主，同时保留精确用户名登录；邮箱不区分大小写。用户可在个人中心修改显示名称和用户名，新建或修改的用户名限制为 3–32 位小写英文字母、数字或下划线，必须以字母开头，且不能与已有用户名重名（含历史大小写变体）；`public` 为系统保留名称。历史用户名不强制改写；改名后画廊地址随之改变，旧链接失效，保存前会明确提醒。

忘记密码通过邮箱验证码直接设置新密码，不需要输入原密码。历史账号如果还没有邮箱，可以登录后在个人中心发送验证码并绑定邮箱；已绑定邮箱不能自行更换，需要由管理员处理。个人中心不提供修改密码入口，管理员仍可在后台直接重置任意用户密码。

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

使用 [Resend SMTP](https://resend.com/docs/send-with-smtp) 时，无需安装 SDK 或修改验证码发送逻辑。先在 Resend 验证自有发信域名，按控制台要求添加 DKIM 与发送记录；CNAME 记录保持“仅 DNS”。创建仅限该域名的 `Sending access` API Key，然后在后端 `.env` 配置：

```dotenv
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USERNAME=resend
SMTP_PASSWORD=replace-with-resend-api-key
SMTP_FROM_EMAIL=no-reply@mail.example.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

`SMTP_FROM_EMAIL` 必须使用已验证的发信域名。Key 仅保存在后端私有环境配置中；更新配置后需让 API 服务重新加载环境。使用项目验证码模板实发到自有邮箱，并在 Resend 邮件记录中确认投递结果，不能仅以 SMTP 接受邮件作为到达收件箱的证据。

网站更换域名时，同步检查 DNS、CDN 域名绑定和证书。CDN 回源 Host 应跟随访问域名，避免固定旧 Host 导致新域名下的认证同源校验失败；认证接口和私有媒体沿用现有的不缓存策略。浏览器的 Cookie、localStorage 与 IndexedDB 按域名隔离，用户需在旧域名导出本地画布，再到新域名导入。

保留旧域名画布导出期间，普通页面（包括直接访问 `/login`）应返回独立迁移提示页，显示“旧站域名即将关停”，5 秒后前往新域名；不能继续加载普通应用页面。保留原路径、参数与片段，并提供立即前往和旧画布导出按钮；进入导出流程时取消倒计时。页面使用 `no-referrer`，避免跳转时携带旧域名来源而被新站防盗链拦截。

迁移响应须排除 `/canvas`、`/canvas/*` 及 API、静态资源、媒体路径；只有明确携带站内画布返回路径的登录页可豁免。旧域名证书、域名绑定和同源回源继续保留。画布路由登录后返回原画布地址，登录页仅接受站内画布返回路径。用户需用原账号在原浏览器中登录旧域名，才能读取该账号原有的本地画布。页面模板与匹配逻辑见 `deploy/cdn/domain-migration.js`；CDN 可用静态 HTML 响应动作配置，匹配条件必须使用 AND，停用重叠的立即跳转规则。边缘脚本需要平台审核时保持停用，避免出现两套配置先后生效。

### 在线充值

ZPAY 商户 ID、密钥、网关、网站公网地址与支付方式在「管理后台 → 充值管理」填写；密钥加密保存、不回显，保存后即时生效。服务器先运行 `python3 scripts/init-payment-encryption-key.py --env-file .env` 初始化独立主密钥，并让 API/worker 重新加载环境。主密钥随私有配置备份，不得直接替换。当前迁移要求 V14；默认收款与预置套餐关闭。

充值套餐、加密配置、回调与漏单补查、付费/赠送额度分摊以及 V13/V14 迁移说明见 [充值中心](recharge-center.md)。默认总开关关闭，预置 10 元 / 100 丝套餐也处于停用状态，由管理员配置后再启用。第三方 Python SDK 的来源、风险与替代实现见 [SDK 安全审查](zpay-sdk-security-review.md)。

### 登录保持与续期

普通用户的访问令牌有效期为 15 分钟；浏览器通过 HttpOnly 刷新 Cookie 自动续期，30 天未使用后失效，单次登录最长 180 天。续期只在可见页面发起 API 或私有素材请求时进行，不使用后台定时器续命。临时网络故障、429、5xx 或 HTML 防护页面不会主动清除登录状态。

刷新 Cookie 仅作用于 `/api/v1/auth`，生产必须使用 HTTPS；`APP_ENV=production` 会启用 Secure，Cookie 同时设置 HttpOnly 和 SameSite=Strict。Cookie 不返回给 JavaScript，数据库不保存可直接使用的刷新令牌。多标签页通过 Web Locks 协调；服务端使用 PostgreSQL 行锁、30 秒并发宽限及重放撤销。

退出会撤销当前浏览器会话；邮箱找回密码或管理员重置密码后，所有新制会话在下一次访问时立即失效。仍有效的旧制令牌在首次请求时迁移，已经过期的旧制令牌需重新登录一次。兼容期内旧制令牌本身仍按原到期时间失效。`JWT_EXPIRE_MINUTES` 继续用于旧制/管理员令牌，新普通用户会话按上述时长执行。

调用登录、注册、`POST /api/v1/auth/session`、`POST /api/v1/auth/refresh` 或 `POST /api/v1/auth/logout` 时须发送 `X-Session-Request: 1`；Cookie 操作须同源。刷新请求不需要 access token；旧制迁移需要仍有效的 Bearer token。禁止 CDN 缓存上述接口或向它们返回交互式浏览器挑战。

v0.21.0 升级新增 V11 会话表，运行正式 tag 的自动部署流程，流程会在停服务及迁移前保存并解析验证数据库快照。V11 不修改已有用户、账务或媒体数据。旧版本的 schema 健康检查仍要求 V10，因此迁移后不能仅换旧镜像就视为健康回退；优先前向修复。必须回退时停写，并按备份与灾难恢复指南评估恢复升级前快照，不删除 Flyway 历史或手工降级 schema。

### Agent / MCP 接入

正式启用前设置 `MCP_PUBLIC_URL=https://painter.example.com/api/mcp`，完成 Flyway V12 后同步启动同版本 API、worker 与 dispatcher。空值关闭 MCP；规范地址变更会使旧授权失效。升级与回退、客户端配置、独立授权和预算规则见 [MCP 接入指南](mcp-integration.md)。代理/CDN 须放行 `/api/mcp`、`/api/oauth/`、`/.well-known/` 和 AI 可读文档，不缓存认证与媒体响应，不对 MCP 客户端返回交互式浏览器挑战。

### 图片浏览

在生成结果的作品详情、历史/画廊/收藏详情、灵感详情及后台任务/投稿原图中，点击图片进入统一的 Naive UI 浏览器。工具栏可连续放大、缩小、旋转、恢复原始尺寸和下载；也可滚轮缩放、拖动查看，方向键上下缩放。Esc 只关闭顶层图片预览，不会连同底层详情一起关闭。

预览复用已鉴权的 Blob，不额外请求私有原图地址。图片到期或切换账号/图片时会关闭浏览器并释放 Blob；已失效的图片不能重新打开预览。列表缩略图仍保留原有“打开详情/选择参考图”的操作。

### 全局生成统计

顶部主导航保留社区灵感、创作台、无限画布；历史、画廊、收藏、Agent、版本及管理入口收进账户菜单。钱包进入个人中心，充值入口位于钱包卡片；个人中心按钱包/兑换、整行用户组权益、账户资料和消费记录排列。

前台内容页面在顶部导航下方展示生成统计，每 5 秒轮播“今日已生成图片 N 张”和“系统运行至今已生成 N 张”，每 60 秒刷新数据。点击可手动切换，悬停或键盘聚焦时暂停轮播。个人中心和充值页隐藏统计，保留系统横幅；无限画布页隐藏统计与横幅，保留完整编辑空间。

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
- 生产备份内容、快照校验和新环境恢复步骤见 [`docs/backup-and-disaster-recovery.md`](backup-and-disaster-recovery.md)。

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

已配置 CD 的环境在正式 tag 的三个镜像构建成功后自动部署，配置和恢复方式见 [CD 指南](continuous-deployment.md)。未配置 CD 时，先按 [README 的发布流程](../README.md#发布) 完成版本更新、测试、提交和 tag，再等待三个版本镜像构建成功。服务器只部署新的正式版本标签：

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

