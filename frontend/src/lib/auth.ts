import { reactive } from 'vue'
import type { TokenResponse, UserInfo } from './types'

const TOKEN_KEY = 'easy-painter:token'
const ADMIN_TOKEN_KEY = 'easy-painter:admin-token'

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

export async function login(username: string, password: string): Promise<void> {
  const response = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error((payload as { detail?: string }).detail || '登录失败。')
  }
  const data = (await response.json()) as TokenResponse
  authState.token = data.access_token
  localStorage.setItem(TOKEN_KEY, data.access_token)
  await fetchCurrentUser()
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
