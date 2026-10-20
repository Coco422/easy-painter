# Agent / MCP 接入

网站入口 `/mcp`。用户在客户端添加服务，浏览器登录后单独授权权限、单次消费上限及 7/30/90 天有效期。网页、普通 API 和 MCP 均不设每日消费上限，已有连接同样适用。网站与 MCP 使用同一账号、模型价格和积分；连接管理支持调整额度与撤销授权。安装配置不包含用户密码或令牌。

Codex、Cursor、Claude 和 dsh 配置统一见站内 `/mcp/install.md`，源码是 `backend/app/agent_content/install.md`。dsh 未内置 OAuth 的 MCP 插件可通过 `mcp-remote@0.15.1` stdio 桥接；桥接负责浏览器授权和自动续期，dsh 对话本身仍需要有效的推理模型登录。页面提供可复制的独立 patch，不覆盖现有 profile。

## 本地预览

此预览使用真实 OAuth、官方 MCP SDK、任务及账务代码，替换为隔离 SQLite 数据、内存限流/对象存储和假图工作器，不连接真实上游或生产服务。它不运行 Flyway，不验证 PostgreSQL 行锁。

```bash
cd backend
uv sync
uv run python ../scripts/preview-mcp.py --web-port 5176
```

另开终端：

```bash
cd frontend
VITE_API_PROXY_TARGET=http://127.0.0.1:18932 npm run dev -- --host 127.0.0.1 --port 5176 --strictPort
```

打开 <http://127.0.0.1:5176/mcp>。体验账号 `demo`、`demo2`，密码均为 `Painter123!`，各有 100 丝假积分。点击「在网页测试连接」可走完整 PKCE 授权、免费查询和单张假图任务；描述包含 `[fail]` 时假图工作器执行失败退款。预览端口冲突时同时修改两条命令的 `--web-port` / `--port`，API 端口可通过脚本 `--port` 和 Vite 代理地址对应修改。

预览只监听回环地址，退出进程后图片不再可用，数据库位于新建的系统临时目录；重启创建另一份隔离数据。这些账号无法登录生产。网页测试的 access token 只存在内存，刷新后需重新授权，不自动重跑生成。

## 启用正式服务

新增依赖：官方 Python `mcp==2.3.0`，通过 `uv.lock` 固定。MCP 使用 Flyway `V12__agent_authorization.sql`，增加 `agent_clients`、`agent_authorizations`、`agent_grants`、`agent_credentials`、`agent_usage` 五张表及索引。当前版本还包含充值 V13 和配置 V14，readiness 期望版本为 **14**。

设置后端环境变量：

```dotenv
MCP_PUBLIC_URL=https://painter.example.com/api/mcp
```

必须是用户访问的完整规范地址，路径固定 `/api/mcp`、无查询串、无末尾斜杠；生产要求 HTTPS。空值禁用接入。开发环境允许回环 HTTP。修改规范地址会使旧授权失效，用户需重新连接。反向代理应保留正确 Host，不缓存认证响应；仓库 nginx 已转发 `/api/`、`/.well-known/` 和下述文档路径。MCP SDK 校验 Host/Origin，默认只接受本站 Origin；服务端客户端通常不发送 Origin，不将授权接口开放为带凭证的跨站 CORS。

存在域名迁移时，先在浏览器确认应用页面最终落地的新站地址，再绑定 MCP。旧站的 API/健康接口仍可能可访问，不能仅凭 API 返回 200 判断正式域名。macOS 的终端 Node 客户端也可能不继承系统代理；浏览器可访问而终端超时时，为当前 dsh 进程设置 `HTTP_PROXY` / `HTTPS_PROXY`，并给 `mcp-remote` 添加 `--enable-proxy`。

生产发布仍需新正式 tag、按 [自动部署](continuous-deployment.md) 保存并校验升级前快照、先执行 V12 再同步启动配套服务。旧版 readiness 期望 V11，不能只切换旧镜像便声称健康回退；按 [备份恢复](backup-and-disaster-recovery.md) 评估，优先前向修复，不删除授权或账务记录。

## 协议与接口

- MCP：`/api/mcp`，官方 SDK 的 stateless Streamable HTTP，六个工具与结构化结果。单次请求体上限 64 KiB，不把长生成留在 HTTP 连接中等待。
- 发现：`/.well-known/oauth-protected-resource[/api/mcp]`、`/.well-known/oauth-authorization-server`。
- OAuth：`/api/oauth/register`、`/authorize`、`/token`、`/revoke`。
- 本站登录态管理：`/api/v1/agent/config`、`/connections`、`/connections/{id}`、`/authorizations/{id}`。
- 安装/能力文档：`/mcp/install.md`、`/llms.txt`、`/llms-full.txt`。
- Skill：`/mcp/skill/SKILL.md`、`/mcp/easy-painter-skill.zip`，同一源码生成压缩包。源码在 `backend/app/agent_content/`，不要另维护一份下载副本。

| 工具 | 权限 | 行为 |
| --- | --- | --- |
| `list_models` | 有效授权 | 可用模型、尺寸、参考能力、用户组价格；免费 |
| `get_balance` | `account:read` | 余额与连接单次消费上限；免费 |
| `estimate_cost` | 有效授权 | 校验模型/尺寸，估算单张价格；免费，提交时重新检查 |
| `generate_image` | `jobs:create` | 单张付费任务；必填 `request_id`、`max_cost` |
| `edit_image` | `jobs:read` + `jobs:create` | 从自己的未过期成图提交单张改图，保留原任务 |
| `get_job` | `jobs:read` | 读取自己已有任务、提示词、计费和结果，免费 |

任务读取权限包含账号已有任务，授权页明确告知；首版不开放管理、删除、公开作品、任意 URL 抓图、本地文件上传、数据绘图、SVG/PPTX 转换或浏览器本地画布/版本关系。

## 授权与消费一致性

OAuth 采用公开客户端动态注册（DCR）、授权码与强制 S256 PKCE；不支持 CIMD 元数据 URL 抓取。注册回调只允许 HTTPS 或回环 HTTP，授权时匹配注册值，IP 回环端口按 RFC 8252 可变化；不会把错误重定向到未验证地址。客户端名称是自报信息，页面同时显示完整回调地址。注册、授权和令牌端点限流，请求体有上限；每用户最多 50 个尚未撤销/到期的连接。

授权码在批准后仅有效 60 秒，只能使用一次，并绑定客户端、精确回调、目标 resource 和 PKCE。访问凭证有效 15 分钟，刷新凭证轮换且不超过用户选定的授权期限；重放已使用的刷新凭证撤销整份授权。数据库只保存随机凭证的 SHA-256 摘要，凭证绑定规范 MCP resource 与密码摘要。改密、授权到期或撤销后拒绝访问/刷新；网页登录 JWT 与 Agent 凭证互不通用。网页退出不等于撤销已独立授予 Agent 的权限。

付费调用沿用 `create_generation_job`：锁账号再锁连接，检查权限、模型当前价格、调用参数 `max_cost`、连接单次上限和账号可用余额，然后在**同一事务**创建任务、预扣、积分流水、outbox 与 `agent_usage`。不按日累计消费额度拦截任务，消费报表与审计保留。额度降低不取消旧任务，也不改变旧价格；撤销同样只阻止后续调用。

旧版数据库的 `agent_grants.daily_limit` 列仅为兼容 V12 约束保留，运行时不作为限额读取，新建/修改连接时填入单次上限以满足旧约束；不需要修改历史迁移或重授权。旧客户端提交的 `daily_limit` 会被忽略，公开请求 schema、连接列表、`get_balance` 和 `estimate_cost` 均不再暴露日额度字段。全站无每分钟生成配额，仅共用账号级秒级洪峰防刷（默认 60 次新提交/秒）；验证码、OAuth 防滥用规则继续生效。

每个连接的 request_id 独立命名空间，参数摘要包含操作源图和 max_cost；同请求重试不重新上传、不重复扣费，即使源图后来过期仍可确认原任务。改变参数必须是新用户意图，不能以换请求 ID 绕过未知结果。客户端/Skill 应先保存完整调用参数和 request_id，再提交；得到 job_id 后只轮询状态。

生成结果的下载地址是单图、单授权的独立短期 capability（最长 5 分钟），不包含 access/refresh token；每次访问重查授权、所有权和原图期限，撤销后链接立即失效。网站历史入口需要正常登录。

注册客户端、授权请求和轮换凭证会累积；正式运行应监控新增表与索引大小。清理已过期请求/凭证前保留必要的安全审计期；不要删除仍有效的刷新重放记录或 `agent_usage`，后者关联消费审计和幂等记录。首版未增加定时清理任务或运营审计界面。

## 验证

```bash
cd backend
uv run pytest
PYTHONPATH=. uv run --with pgserver==0.1.4 python ../scripts/check-mcp-postgres.py
```

第二条使用测试专用临时依赖，不写项目依赖，不访问现有数据库：创建独立 PostgreSQL 16，执行仓库现有全部迁移 SQL，验证超过旧日限额的并发提交、余额不足拒绝与相同请求并发重放，随后停掉该临时实例。它验证 SQL 和真实 PostgreSQL 锁，不替代发布镜像中的 Flyway runner 验证。

```bash
cd frontend
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build
node --experimental-strip-types --test tests/*.test.mjs
```

端到端验收应覆盖：发现与注册 → 浏览器授权 → 免费查询 → 生成/查询/下载 → 原请求重试 → 改图 → 超过旧日限额仍能生成 → 单次上限/余额不足拒绝 → 失败退款 → 降额和撤销。实际三方客户端及真实上游验收应分别记录，不能用本地假图代替。

客户端配置以官方说明为准：[Codex](https://developers.openai.com/codex/mcp/)、[Cursor 安装链接](https://cursor.com/docs/mcp/install-links)、[MCP 授权](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)。页面布局参考 OpenDesign 的 Linear 规范，使用 4 px 间距、24 px 栅格间隔、6/12 px 圆角和细分隔线，保留本站主题色。

本地预览启动后还可以从 `backend/` 执行 `uv run python ../scripts/check-mcp-preview.py`，用官方 SDK 的默认协议走真实 HTTP，验证生成、改图、重放、累计消费超过旧日限额、单次上限拒绝和撤销。脚本固定访问本机 5176，且在模型不是 `mock-image` 时拒绝运行，不调用真实上游。

取消日/分钟配额后的本地验证：后端 325 项、前端 60 项测试及构建通过；PostgreSQL 16 并发累计接受 20 笔任务，用完 100 丝余额，另外 4 笔请求因余额不足拒绝，8 次并发重放仍返回原任务。HTTP SDK 的生成、改图、超旧日限额提交、单次上限拒绝和撤销均通过。浏览器自定义批量 13 张假图全部成功；秒级洪峰拒绝、1 秒后恢复与跨入口共享防刷计数的回归测试通过。本段为本地实现记录；生产验收以对应正式版本的部署记录为准。

### 2026-10-20 v0.23.0 发布前验收（历史记录）

以下记录对应 v0.23.0 的旧日限额策略；当前实现已取消每日消费上限。

- dsh 桌面附带 CLI `0.2.1-rc.2`、原生 `dsh-mcp-client` 和 `mcp-remote@0.15.1` 实际连接，浏览器完成 OAuth；通过 dsh 工具执行管线做确定性断言。没有把推理模型登录失效时的对话运行描述为成功。
- 隔离账号、数据库与对象存储中调用真实 `gpt-image-2-c` 上游：一张 PNG 成功交付，预扣转结算 2 丝，余额 100 → 98；完全相同请求重放返回同一任务；低于报价的 max_cost 与每日超额提交均拒绝，未重复扣费。
- 强制客户端缓存过期后，dsh 桥接成功轮换访问与刷新凭证；撤销后 MCP 返回 401、原图片链接返回 404、刷新返回 400。
- 独立 PostgreSQL 16 容器使用 Flyway 11.10 实际执行 V1–V12，历史表确认 `12 / success`；另有 PostgreSQL 并发额度/重放断言。上述隔离测试不替代上线后的真实 worker、RustFS 与公网代理冒烟。

### 2026-10-20 v0.23.0 生产验收（历史记录）

- 独立发布快照：后端 226 项、前端 47 项、部署脚本 4 项测试通过，前端构建和版本检查通过。正式 tag 的三镜像构建、自动部署及 GitHub Release 成功；API、worker、dispatcher、nginx 均固定 v0.23.0，readiness 为 schema 12。
- 经公网代理走 dsh 原生 MCP 管线，独立测试账号通过真实 worker 和 RustFS 生成、下载一张 `gpt-image-2` PNG，结算 2 丝，余额 2 → 0。重复原请求仍为同一任务；低报价及每日超额提交均拒绝。
- 生产凭证自动续期成功；网页 JWT 与 MCP 凭证互不通用。测试连接已撤销，MCP/原图/刷新分别拒绝为 401/404/400；没有遗留有效测试授权。升级前数据库与配置快照存在，数据库 SHA-256 校验通过。
