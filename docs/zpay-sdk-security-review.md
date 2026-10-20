# ZPAY SDK 审查与接入决定

审查日期：2026-10-20。对象是 [h053698/z-pay-python](https://github.com/h053698/z-pay-python) 与 PyPI `zpay==0.1.1`，并对照 [ZPAY 接口文档](https://z-pay.cn/doc.html)。这是定向源码审查与本项目安全测试，不是对支付服务商资金安全的认证。

## 来源与版本

- PyPI 署名个人作者 Yuchan Han，维护账号 `h053698`，发布状态为 Alpha。未找到 ZPAY 官方为该仓库背书的证据，按第三方封装处理。
- 官方文档另提供 `cdn.z-pay.cn/download/python.zip` 示例下载；这不能证明第三方包为官方 SDK。
- PyPI 0.1.1 源码包 SHA-256：`31c6d6e2343aadd90932a3787093e7628776c476952c34fff1f3c9a339fbac84`。
- 审查时 GitHub main 归档 SHA-256：`e7b8b5ee3eed28579cd5c2e7a247c66b55bec0fcedb54873c4d1857228adbb66`。五个核心 Python 文件与 PyPI 0.1.1 逐字节一致。
- README 与 PyPI 声明 MIT；本项目没有复制或安装该包源码，也没有新增它的 `aiohttp` 依赖。

## 发现与处理

| 发现 | 影响和项目处理 |
|---|---|
| `signature.py` 直接使用原始 `key=value&...` 拼接，未拒绝歧义分隔符 | `a=1&b=2&c=3` 可来自两组不同参数，例如 `a` 的值包含 `&b=2`。这是 v1 签名格式风险；本项目拒绝值中的 `&`、控制字符和重复字段，并再次向平台查单，不单靠回调发放额度 |
| `verify_sign` 使用普通字符串相等比较 | 本项目使用 `hmac.compare_digest`，严格要求 MD5 与合法签名格式 |
| `verify_notification` 仅验签、把缺失字段转为空字符串 | 商户、金额、订单归属和成功状态仍须业务方核验；本项目逐项检查本地快照、回调和主动查单结果，禁止从浏览器跳转直接加丝 |
| `base_url` 接受任意字符串，未强制 HTTPS；HTTP 客户端未禁用重定向 | 查单依协议在 GET 参数中带商户密钥。错误网关或跨域重定向会扩大密钥泄露风险；本项目只允许 HTTPS 根网关，禁用重定向与环境代理 |
| 未显式设置短网络超时和响应体上限 | 本项目设置连接/读取超时及 64 KiB 响应上限；错误只向业务层返回固定错误码 |
| 金额以任意字符串传入、响应模型不是严格校验模型 | 本项目金额使用整数分；平台金额由 Decimal 严格转换，拒绝浮点、科学计数法、负数、超精度和非有限值 |
| SDK 不提供交易幂等、数据库锁与账户账本 | 本项目负责订单唯一键、平台流水唯一键、用户→订单行锁，以及同事务确认订单、加丝、创建额度来源 |

已阅读五个核心模块，未发现遥测、额外密钥外传目标、动态执行或主动后门代码；这不等于该 SDK 可以脱离业务校验直接用于资金入账。

## 实施决定

不直接安装第三方 SDK。使用项目已有 `httpx` 实现 `backend/app/services/zpay.py`，遵守 ZPAY v1 协议：页面 POST 到托管收银台、后台主动查单、回调双重核验。

ZPAY v1 的查询接口要求在 GET 中携带商户密钥，因此后端日志过滤器必须继续生效；动态配置密钥按查询字段脱敏，Uvicorn 访问日志同样过滤签名，Nginx 访问日志不保存查询参数或 Referer。不要记录完整请求 URL、原始通知、密钥或支付签名。API 不向前端返回商户密钥。V14 将后台填写的商户密钥通过 Fernet 认证加密后存库，独立主密钥仅在私有环境配置，旧订单绑定原配置版本；操作与恢复要求见 [充值中心](recharge-center.md)。

## 验证入口

- `cd backend && uv run pytest tests/test_payments.py -q`：金额、验签、重复参数、商户/订单匹配、查单失败、重复到账、越权、套餐快照和额度来源回归。
- `cd backend && PYTHONPATH=. uv run --with pgserver==0.1.4 python ../scripts/check-payments-postgres.py`：隔离 PostgreSQL 的迁移 SQL 与并发到账/退丝演练。
- `cd frontend && node --experimental-strip-types --test tests/recharge.test.mjs`：金额输入转换和返回路径约束。
