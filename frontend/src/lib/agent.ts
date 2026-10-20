import { authenticatedFetch } from './auth'
import { randomId, sha256Hex } from './browser-crypto'

export interface AgentConnection {
  id: string; label: string; scopes: string[]; max_per_job: number; daily_limit: number
  used_today: number; created_at: string; expires_at: string; active: boolean
}
export interface AgentConfig { enabled: boolean; endpoint: string | null; scopes: Record<string, string> }
export async function agentApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authenticatedFetch(`/api/v1/agent${path}`, {
    ...init, headers: { 'Content-Type': 'application/json', 'X-Session-Request': '1', ...init.headers },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message ?? `请求失败（${response.status}）`)
  }
  return response.status === 204 ? undefined as T : response.json()
}
const quote = (value: string) => `'${value.replace(/'/g, "'\"'\"'")}'`
export function installation(client: string, endpoint: string): { text: string; link?: string; hint: string } {
  if (client === 'cursor') return {
    text: JSON.stringify({ mcpServers: { 'easy-painter': { url: endpoint } } }, null, 2),
    link: `cursor://anysphere.cursor-deeplink/mcp/install?name=easy-painter&config=${encodeURIComponent(btoa(JSON.stringify({ url: endpoint })))}`,
    hint: '点击安装后，在 Cursor 内确认添加，再完成浏览器授权。也可把下面配置合并到 mcp.json。',
  }
  if (client === 'codex') return { text: `codex mcp add easy-painter --url ${quote(endpoint)}\ncodex mcp login easy-painter --oauth-client-registration dcr`, hint: '复制到支持 OAuth 的新版 Codex CLI 执行，浏览器会打开本站授权页。桌面端也可在 MCP 设置中添加这个服务地址。' }
  if (client === 'claude') return { text: `claude mcp add --transport http easy-painter ${quote(endpoint)}`, hint: '在 Claude Code 的项目终端执行，再通过 /mcp 完成授权。Claude 网页或桌面版可在自定义连接器中添加服务地址。' }
  if (client === 'dsh') return {
    text: `- insert:\n  - id: mcp-easy-painter\n    name: '@deepseek-ai/dsh-mcp-client'\n    config:\n      serverName: easy_painter\n      transport: stdio\n      command: npx\n      args: ['-y', 'mcp-remote@0.15.1', ${quote(endpoint)}, '--host', '127.0.0.1', '--transport', 'http-only']\n      failOnStartupError: true`,
    hint: '保存为 easy-painter.yml，再运行 dsh --profile headless --patch ./easy-painter.yml "查看绘图模型和余额"。首次连接会打开浏览器授权；mcp-remote 负责 OAuth 和续期，需要 Node.js 与 npm。不要覆盖已有配置。',
  }
  return { text: endpoint, hint: '在支持远程 Streamable HTTP 与 OAuth 的客户端中添加此地址。云端客户端无法访问你电脑上的 127.0.0.1，需要已部署的 HTTPS 服务。' }
}

export async function startConnectionTest(endpoint: string) {
  const verifier = randomId().replace(/-/g, '') + randomId().replace(/-/g, '')
  const state = randomId()
  const rawHash = await sha256Hex(new TextEncoder().encode(verifier).buffer as ArrayBuffer)
  const bytes = Uint8Array.from(rawHash.match(/../g)!, item => parseInt(item, 16))
  const challenge = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
  const origin = new URL(endpoint).origin
  if (origin !== location.origin) throw new Error('连接测试需从 MCP 配置的正式站点地址打开。')
  const redirect = origin + '/mcp/callback'
  const response = await fetch('/api/oauth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_name: '网页连接测试', redirect_uris: [redirect], token_endpoint_auth_method: 'none' }) })
  if (!response.ok) throw new Error('测试客户端注册失败，请稍后重试。')
  const { client_id: clientId } = await response.json()
  sessionStorage.setItem('easy-painter:agent-test', JSON.stringify({ verifier, state, clientId, redirect, endpoint }))
  location.assign('/api/oauth/authorize?' + new URLSearchParams({ client_id: clientId, redirect_uri: redirect, response_type: 'code', code_challenge: challenge, code_challenge_method: 'S256', state, resource: endpoint, scope: 'account:read jobs:read jobs:create' }))
}

export class AgentToolError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'AgentToolError' }
}

export async function mcpRpc(endpoint: string, token: string, method: string, params: Record<string, unknown> = {}) {
  const response = await fetch(endpoint, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25' }, body: JSON.stringify({ jsonrpc: '2.0', id: randomId(), method, params }) })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.error) throw new Error(data.error?.message ?? data.error_description ?? `MCP 请求失败（${response.status}）`)
  if (data.result?.isError) {
    const message = data.result.content?.map((item: { text?: string }) => item.text ?? '').join('\n') ?? '工具执行失败'
    let detail: { status?: number; detail?: string | { message?: string } } = {}
    try { detail = JSON.parse(message.slice(Math.max(0, message.indexOf('{')))) } catch { /* Preserve non-JSON SDK validation errors. */ }
    throw new AgentToolError(typeof detail.detail === 'string' ? detail.detail : detail.detail?.message ?? message, detail.status ?? 0)
  }
  return data.result
}
export async function callTool(endpoint: string, token: string, name: string, args: Record<string, unknown> = {}) {
  const result = await mcpRpc(endpoint, token, 'tools/call', { name, arguments: args })
  if (result.structuredContent) return result.structuredContent
  return JSON.parse(result.content.find((item: { type: string }) => item.type === 'text').text)
}
