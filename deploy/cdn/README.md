# 域名迁移提示页

`domain-migration.js` 包含独立 HTML 模板和 GoEdge 请求匹配逻辑。部署时在私有运维副本中替换 `migrationConfig`，真实主机名不写入仓库。

可将生成的 HTML 配置为 CDN 的静态页面响应（HTTP 200），无需运行服务端边缘脚本。客户端在 5 秒后通过 `location.replace` 前往新站，保留路径、查询参数和片段；导出链接保留在旧源并取消倒计时。页面没有应用 bundle、登录表单或 API 请求，使用 `no-referrer` 避免新站防盗链误拦截。

静态响应的匹配条件必须为 **AND**：

- 主机名为本次迁移的旧域名。
- 请求方法为 GET 或 HEAD。
- 路径不匹配 `^/(api|assets|media|canvas)(/|$)`。
- URI 不属于明确返回站内画布的登录恢复请求。

先在停用的独立分组中配置并核对条件；开启后验证旧登录页、新站、旧画布、API 和实际倒计时。停用重叠的立即跳转规则。回退时停用迁移分组并恢复原跳转规则，不删除旧域名绑定、证书或存储。

如果直接使用 GoEdge 边缘脚本，需要等待平台审核后才能生效；静态响应已启用时应保持脚本停用。只启用当前迁移所需的自定义规则，不引入额外全局规则。

验证命令：

```bash
cd frontend
node --experimental-strip-types --test tests/domain-migration.test.mjs
```
