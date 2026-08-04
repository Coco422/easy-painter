import { reactive } from 'vue'
import type { EmailCodePurpose, EmailCodeResponse, TokenResponse, UserInfo } from './types'

const TOKEN_KEY = 'easy-painter:token'
const ADMIN_TOKEN_KEY = 'easy-painter:admin-token'

export class AuthApiError extends Error {
  constructor(message: string, readonly retryAfter?: number) {
    super(message)
    this.name = 'AuthApiError'
  }
}

export const authState = reactive({
  token: localStorage.getItem(TOKEN_KEY) || null,
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

async function applyUserToken(data: TokenResponse): Promise<void> {
  authState.token = data.access_token
  localStorage.setItem(TOKEN_KEY, data.access_token)
  await fetchCurrentUser()
}

export async function login(identifier: string, password: string): Promise<void> {
  const response = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: identifier, password }),
  })
  if (!response.ok) {
    throw new Error(await errorMessage(response, '登录失败。'))
  }
  await applyUserToken((await response.json()) as TokenResponse)
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
  const response = await fetch('/api/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    throw new Error(await errorMessage(response, '注册失败。'))
  }
  await applyUserToken((await response.json()) as TokenResponse)
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
  authState.token = null
  authState.user = null
  localStorage.removeItem(TOKEN_KEY)
}

export async function fetchCurrentUser(): Promise<void> {
  if (!authState.token) {
    authState.user = null
    return
  }
  try {
    const response = await fetch('/api/v1/users/me', {
      headers: { Authorization: `Bearer ${authState.token}` },
    })
    if (!response.ok) {
      authState.token = null
      authState.user = null
      localStorage.removeItem(TOKEN_KEY)
      return
    }
    authState.user = (await response.json()) as UserInfo
  } catch {
    authState.user = null
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
