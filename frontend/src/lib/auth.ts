import { reactive } from 'vue'
import type { EmailCodePurpose, EmailCodeResponse, TokenResponse, UserInfo } from './types'

const TOKEN_KEY = 'easy-painter:token'
const ADMIN_TOKEN_KEY = 'easy-painter:admin-token'

type AccessClaims = { sub?: string; sid?: string; typ?: string; exp?: number }
function claims(token: string | null): AccessClaims {
  try {
    const payload = JSON.parse(atob((token?.split('.')[1] ?? '').replace(/-/g, '+').replace(/_/g, '/')))
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {}
  }
  catch { return {} }
}
function sessionIdentity(token: string | null): string | null {
  if (!token) return null
  const payload = claims(token)
  return payload.sid ?? token // Legacy credentials change identity once on migration.
}

export class AuthApiError extends Error {
  constructor(message: string, readonly retryAfter?: number) {
    super(message)
    this.name = 'AuthApiError'
  }
}

export const authState = reactive({
  token: localStorage.getItem(TOKEN_KEY) || null,
  sessionId: sessionIdentity(localStorage.getItem(TOKEN_KEY)),
  user: null as UserInfo | null,
  adminToken: localStorage.getItem(ADMIN_TOKEN_KEY) || null,
})

export function getAuthHeader(): Record<string, string> {
  return authState.token ? { Authorization: `Bearer ${authState.token}` } : {}
}

export function getAdminAuthHeader(): Record<string, string> {
  return authState.adminToken ? { Authorization: `Bearer ${authState.adminToken}` } : {}
}

export function isLoggedIn(): boolean {
  return Boolean(authState.token)
}

export function isAdmin(): boolean {
  return Boolean(authState.adminToken)
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => ({}))
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined
    if (typeof first?.msg === 'string') {
      return first.msg.replace(/^Value error,\s*/i, '')
    }
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string') return message
  }
  return fallback
}

function setUserToken(token: string | null): void {
  const identity = sessionIdentity(token)
  if (identity !== authState.sessionId) authState.user = null
  authState.token = token
  authState.sessionId = identity
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

window.addEventListener('storage', event => {
  if (event.key === TOKEN_KEY || event.key === null) {
    setUserToken(localStorage.getItem(TOKEN_KEY))
  }
})

function applicationUnauthorized(response: Response): boolean {
  return response.status === 401 && (response.headers.get('Content-Type') ?? '').includes('application/json')
}

let authOperation = 0
let localSessionLock: Promise<void> = Promise.resolve()
async function withSessionLock<T>(action: () => Promise<T>): Promise<T> {
  if (navigator.locks) return await navigator.locks.request('easy-painter:session', action)
  const previous = localSessionLock
  let release!: () => void
  localSessionLock = new Promise(resolve => { release = resolve })
  await previous
  try { return await action() } finally { release() }
}

let refreshPending: Promise<void> | null = null
function refreshAccessToken(rejectedToken: string): Promise<void> {
  if (refreshPending) return refreshPending
  const renew = async () => {
    setUserToken(localStorage.getItem(TOKEN_KEY))
    if (authState.token !== rejectedToken) return
    const payload = claims(rejectedToken)
    const legacy = !payload.sid && !payload.typ && (payload.exp ?? 0) > Date.now() / 1000
    const response = await fetch(legacy ? '/api/v1/auth/session' : '/api/v1/auth/refresh', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-Session-Request': '1', ...(legacy ? getAuthHeader() : {}) },
    })
    // Ignore replies from a previous login/logout, including a refresh in flight.
    if (authState.token !== rejectedToken || localStorage.getItem(TOKEN_KEY) !== rejectedToken) return
    if (!response.ok) {
      if (applicationUnauthorized(response)) setUserToken(null)
      throw new Error(await errorMessage(response, '登录续期暂时失败，请稍后重试。'))
    }
    const data = await response.json() as TokenResponse
    if (typeof data.access_token !== 'string' || !data.access_token) throw new Error('登录续期响应无效。')
    const next = claims(data.access_token)
    if (!next.sid || next.typ !== 'access' || next.sub !== payload.sub || (payload.sid && next.sid !== payload.sid)) {
      throw new Error('登录续期会话不匹配，请重新登录。')
    }
    if (authState.token === rejectedToken && localStorage.getItem(TOKEN_KEY) === rejectedToken) setUserToken(data.access_token)
  }
  const pending = withSessionLock(renew).finally(() => { refreshPending = null })
  refreshPending = pending
  return pending
}

/** Only real same-origin requests refresh; hidden-tab polling never extends a session. */
export async function authenticatedFetch(url: string, init?: RequestInit): Promise<Response> {
  const target = new URL(url, window.location.origin)
  if (target.origin !== window.location.origin || !target.pathname.startsWith('/api/')) {
    throw new Error('不支持的认证请求地址。')
  }
  const operation = authOperation
  const initialIdentity = authState.sessionId
  const original = authState.token
  const payload = claims(original)
  const visible = document.visibilityState !== 'hidden'
  const legacy = Boolean(original && !payload.sid && !payload.typ && payload.exp)
  if (original && visible && (legacy || (payload.exp ?? Infinity) < Date.now() / 1000 + 60)) {
    await refreshAccessToken(original)
    // A legacy exchange intentionally introduces a session id for this account.
    if (operation !== authOperation || !authState.token || (legacy && claims(authState.token).sub !== payload.sub) || (!legacy && authState.sessionId !== initialIdentity)) throw new Error('登录状态已变化。')
  }
  if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  const identity = authState.sessionId
  const token = authState.token
  const send = () => {
    const headers = new Headers(init?.headers)
    headers.delete('Authorization')
    for (const [key, value] of Object.entries(getAuthHeader())) headers.set(key, value)
    return fetch(url, { ...init, headers, credentials: 'same-origin' })
  }
  let response = await send()
  if (token && visible && applicationUnauthorized(response)) {
    await refreshAccessToken(token)
    if (!authState.token || authState.sessionId !== identity) throw new Error('登录状态已变化。')
    if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    response = await send() // Exactly once, preserving the original body and idempotency key.
  }
  if (operation !== authOperation || authState.sessionId !== identity) throw new Error('登录状态已变化。')
  return response
}

async function signIn(url: string, body: unknown): Promise<void> {
  const operation = ++authOperation
  await withSessionLock(async () => {
    const response = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Session-Request': '1' },
      body: JSON.stringify(body),
    })
    if (!response.ok) throw new Error(await errorMessage(response, '登录失败。'))
    const data = await response.json() as TokenResponse
    if (operation !== authOperation) return
    if (!data.access_token || !claims(data.access_token).sid) throw new Error('登录响应无效。')
    setUserToken(data.access_token)
  })
  if (operation === authOperation) await fetchCurrentUser()
}

export async function login(identifier: string, password: string): Promise<void> {
  await signIn('/api/v1/auth/login', { username: identifier, password })
}

export async function requestEmailCode(email: string, purpose: EmailCodePurpose): Promise<EmailCodeResponse> {
  const response = await fetch('/api/v1/auth/email-codes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, purpose }),
  })
  if (!response.ok) {
    const retryAfterHeader = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
    throw new AuthApiError(
      await errorMessage(response, '验证码发送失败。'),
      Number.isFinite(retryAfterHeader) && retryAfterHeader > 0 ? retryAfterHeader : undefined,
    )
  }
  return (await response.json()) as EmailCodeResponse
}

export async function register(data: {
  username: string
  email: string
  email_code: string
  password: string
  display_name?: string
}): Promise<void> {
  await signIn('/api/v1/auth/register', data)
}

export async function resetPassword(data: {
  email: string
  email_code: string
  new_password: string
}): Promise<void> {
  const response = await fetch('/api/v1/auth/password/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    throw new Error(await errorMessage(response, '密码重置失败。'))
  }
}

export async function logout(): Promise<void> {
  // Clear locally immediately. A failed server logout is surfaced rather than
  // claiming the HttpOnly credential has been revoked.
  authOperation++
  setUserToken(null)
  const revoke = async () => {
    const response = await fetch('/api/v1/auth/logout', {
      method: 'POST', credentials: 'same-origin', headers: { 'X-Session-Request': '1' },
    })
    if (!response.ok) throw new Error(await errorMessage(response, '退出未能同步到服务器，请重试。'))
  }
  if (!navigator.locks) await refreshPending?.catch(() => undefined)
  await withSessionLock(revoke)
}

export async function fetchCurrentUser(): Promise<void> {
  if (!authState.token) { authState.user = null; return }
  try {
    const response = await authenticatedFetch('/api/v1/users/me')
    if (!response.ok) return // Transient failures and edge challenges must retain credentials.
    const identity = authState.sessionId
    const user = await response.json() as UserInfo
    if (authState.token && identity === authState.sessionId && user.id === claims(authState.token).sub) authState.user = user
  } catch {
    // Refresh clears credentials only on an explicit application 401.
  }
}

export async function adminVerify(secretKey: string): Promise<void> {
  const response = await fetch('/api/v1/admin/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ secret_key: secretKey }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error((payload as { detail?: string }).detail || '验证失败。')
  }
  const data = (await response.json()) as TokenResponse
  authState.adminToken = data.access_token
  localStorage.setItem(ADMIN_TOKEN_KEY, data.access_token)
}

export function adminLogout(): void {
  authState.adminToken = null
  localStorage.removeItem(ADMIN_TOKEN_KEY)
}
