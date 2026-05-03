import { getAdminAuthHeader, getAuthHeader } from './auth'
import type {
  AdminJobItem,
  CreateJobRequest,
  CreateJobResponse,
  GalleryItem,
  JobDetailResponse,
  ModelConfig,
  PublicMetaResponse,
  UpstreamProvider,
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

  if (response.status === 204) return undefined as T
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

export function fetchPublicDiscovery(sort: 'recent' | 'liked' = 'recent') {
  return apiRequest<GalleryItem[]>(`/api/v1/gallery?scope=public&sort=${sort}`)
}

export function deleteJob(jobId: string) {
  return apiRequest<void>(`/api/v1/jobs/${jobId}`, { method: 'DELETE' })
}

export function toggleJobPublic(jobId: string) {
  return apiRequest<{ is_public: boolean }>(`/api/v1/jobs/${jobId}/public`, { method: 'PUT' })
}

export function toggleJobFavorite(jobId: string) {
  return apiRequest<{ is_favorite: boolean }>(`/api/v1/jobs/${jobId}/favorite`, { method: 'PUT' })
}

export function likeGalleryItem(jobId: string) {
  return apiRequest<{ like_count: number }>(`/api/v1/gallery/${jobId}/like`, { method: 'POST' })
}

export function unlikeGalleryItem(jobId: string) {
  return apiRequest<void>(`/api/v1/gallery/${jobId}/like`, { method: 'DELETE' })
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

export function adminUpdateUser(userId: string, data: { password?: string; display_name?: string; is_public?: boolean }) {
  return adminApiRequest<UserInfo>(`/api/v1/admin/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export function adminDeleteUser(userId: string) {
  return adminApiRequest<void>(`/api/v1/admin/users/${userId}`, { method: 'DELETE' })
}

// ---- Admin Provider APIs ----

export function adminFetchProviders() {
  return adminApiRequest<UpstreamProvider[]>('/api/v1/admin/providers')
}

export function adminCreateProvider(data: {
  name: string
  base_url: string
  api_key: string
  timeout_seconds?: number
  default_size?: string
  default_quality?: string
  default_output_format?: string
  default_output_compression?: number
  default_background?: string
  default_moderation?: string
}) {
  return adminApiRequest<UpstreamProvider>('/api/v1/admin/providers', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminUpdateProvider(providerId: string, data: Partial<UpstreamProvider>) {
  return adminApiRequest<UpstreamProvider>(`/api/v1/admin/providers/${providerId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export function adminDeleteProvider(providerId: string) {
  return adminApiRequest<void>(`/api/v1/admin/providers/${providerId}`, { method: 'DELETE' })
}

// ---- Admin Model APIs ----

export function adminFetchModels() {
  return adminApiRequest<ModelConfig[]>('/api/v1/admin/models')
}

export function adminCreateModel(data: {
  id: string
  provider_id: string
  label: string
  enabled?: boolean
  supports_reference_image?: boolean
  supported_sizes?: string[]
  sort_order?: number
}) {
  return adminApiRequest<ModelConfig>('/api/v1/admin/models', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminUpdateModel(modelId: string, data: Partial<ModelConfig>) {
  return adminApiRequest<ModelConfig>(`/api/v1/admin/models/${modelId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export function adminDeleteModel(modelId: string) {
  return adminApiRequest<void>(`/api/v1/admin/models/${modelId}`, { method: 'DELETE' })
}
