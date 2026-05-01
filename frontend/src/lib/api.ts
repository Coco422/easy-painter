import { getAdminAuthHeader, getAuthHeader } from './auth'
import type {
  AdminJobItem,
  CreateJobRequest,
  CreateJobResponse,
  GalleryItem,
  JobDetailResponse,
  PublicMetaResponse,
  UserInfo,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const auth = getAuthHeader()
  for (const [key, value] of Object.entries(auth)) {
    headers.set(key, value)
  }
  if (!(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let message = '请求未能完成，请稍后重试。'
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) {
        message = payload.detail
      }
    } catch {
      // Keep the generic message.
    }
    throw new ApiError(message, response.status)
  }

  return (await response.json()) as T
}

export function fetchPublicMeta() {
  return apiRequest<PublicMetaResponse>('/api/v1/meta/public')
}

export function createJob(payload: CreateJobRequest) {
  if (payload.reference_image) {
    const formData = new FormData()
    formData.append('prompt', payload.prompt)
    formData.append('model', payload.model)
    formData.append('size', payload.size)
    formData.append('reference_image', payload.reference_image)
    return apiRequest<CreateJobResponse>('/api/v1/jobs', {
      method: 'POST',
      body: formData,
    })
  }

  return apiRequest<CreateJobResponse>('/api/v1/jobs', {
    method: 'POST',
    body: JSON.stringify({
      prompt: payload.prompt,
      model: payload.model,
      size: payload.size,
    }),
  })
}

export function fetchJob(jobId: string) {
  return apiRequest<JobDetailResponse>(`/api/v1/jobs/${jobId}`)
}

export function fetchGallery() {
  return apiRequest<GalleryItem[]>('/api/v1/gallery')
}

export function fetchPublicGallery(username: string) {
  return apiRequest<GalleryItem[]>(`/api/v1/gallery/${username}`)
}

export function updateProfile(data: { display_name?: string; is_public?: boolean }) {
  return apiRequest<UserInfo>('/api/v1/users/me', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

// Admin APIs use separate admin token
async function adminApiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const auth = getAdminAuthHeader()
  for (const [key, value] of Object.entries(auth)) {
    headers.set(key, value)
  }
  if (!(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, { ...init, headers })

  if (!response.ok) {
    let message = '请求未能完成。'
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {}
    throw new ApiError(message, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function adminFetchJobs() {
  return adminApiRequest<AdminJobItem[]>('/api/v1/admin/jobs')
}

export function adminDeleteJob(jobId: string) {
  return adminApiRequest<void>(`/api/v1/admin/jobs/${jobId}`, { method: 'DELETE' })
}

export function adminFetchUsers() {
  return adminApiRequest<UserInfo[]>('/api/v1/admin/users')
}

export function adminCreateUser(data: { username: string; password: string; display_name?: string }) {
  return adminApiRequest<UserInfo>('/api/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}
