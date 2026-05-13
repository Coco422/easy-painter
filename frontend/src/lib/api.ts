import { getAdminAuthHeader, getAuthHeader } from './auth'
import type {
  AdminJobItem,
  BatchCreateInspirationsResponse,
  CreateJobRequest,
  CreateJobResponse,
  CreditTransactionItem,
  GalleryItem,
  GalleryPageResponse,
  InspirationFeedResponse,
  JobDetailResponse,
  ModelConfig,
  PublicMetaResponse,
  RedemptionCodeItem,
  UpstreamProvider,
  UserInfo,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get required(): number | undefined {
    return this.detail?.required as number | undefined
  }

  get balance(): number | undefined {
    return this.detail?.balance as number | undefined
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
    let detail: Record<string, unknown> | undefined
    try {
      const payload = (await response.json()) as { detail?: string | Record<string, unknown> }
      if (payload.detail) {
        if (typeof payload.detail === 'string') {
          message = payload.detail
        } else {
          detail = payload.detail as Record<string, unknown>
          message = (detail.message as string) ?? message
        }
      }
    } catch {
      // Keep the generic message.
    }
    throw new ApiError(message, response.status, detail)
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

export function fetchActiveJobs() {
  return apiRequest<JobDetailResponse[]>('/api/v1/jobs/active')
}

export function fetchGallery(params: {
  page?: number
  page_size?: number
  q?: string
  from_date?: string
  to_date?: string
} = {}) {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.q) qs.set('q', params.q)
  if (params.from_date) qs.set('from_date', params.from_date)
  if (params.to_date) qs.set('to_date', params.to_date)
  return apiRequest<GalleryPageResponse>(`/api/v1/gallery?${qs}`)
}

export function fetchPublicGallery(params: {
  sort?: 'recent' | 'liked'
  offset?: number
  limit?: number
} = {}) {
  const qs = new URLSearchParams()
  if (params.sort) qs.set('sort', params.sort)
  if (params.offset) qs.set('offset', String(params.offset))
  if (params.limit) qs.set('limit', String(params.limit))
  return apiRequest<GalleryItem[]>(`/api/v1/gallery/public?${qs}`)
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

export function fetchUserGallery(username: string) {
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


export function adminDeleteJob(jobId: string) {
  return adminApiRequest<void>(`/api/v1/admin/jobs/${jobId}`, { method: 'DELETE' })
}

export function adminFetchJobs(statusFilter?: string) {
  const params = statusFilter ? `?status=${statusFilter}` : ''
  return adminApiRequest<AdminJobItem[]>(`/api/v1/admin/jobs${params}`)
}

export function adminBatchDeleteJobs(jobIds: string[]) {
  return adminApiRequest<{ deleted: number; failed: string[] }>('/api/v1/admin/jobs/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ job_ids: jobIds }),
  })
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
  credit_cost?: number
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

// ---- Billing APIs ----

export function redeemCode(code: string) {
  return apiRequest<{ credits: number; added: number }>('/api/v1/users/me/redeem', {
    method: 'POST',
    body: JSON.stringify({ code }),
  })
}

export function fetchCreditHistory(page = 1) {
  return apiRequest<{ items: CreditTransactionItem[]; total: number }>(`/api/v1/users/me/credits?page=${page}`)
}

// ---- Admin Billing APIs ----

export function adminGenerateCodes(data: { count: number; credits: number; prefix?: string }) {
  return adminApiRequest<{ codes: string[] }>('/api/v1/admin/codes/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminFetchCodes(statusFilter: 'all' | 'unused' | 'used' = 'all') {
  return adminApiRequest<RedemptionCodeItem[]>(`/api/v1/admin/codes?status=${statusFilter}`)
}

export function adminAdjustCredits(userId: string, data: { amount: number; reason?: string }) {
  return adminApiRequest<{ credits: number }>(`/api/v1/admin/users/${userId}/credits`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminFetchTransactions(userId?: string, page = 1) {
  const params = new URLSearchParams({ page: String(page) })
  if (userId) params.set('user_id', userId)
  return adminApiRequest<(CreditTransactionItem & { id: string; user_id: string; username: string | null })[]>(
    `/api/v1/admin/transactions?${params}`,
  )
}

// --- Inspiration APIs ---

export function fetchInspirations(params: {
  offset?: number
  limit?: number
  q?: string
  category?: string
  source?: string
  sort?: 'recent' | 'featured'
} = {}): Promise<InspirationFeedResponse> {
  const qs = new URLSearchParams()
  if (params.offset) qs.set('offset', String(params.offset))
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.q) qs.set('q', params.q)
  if (params.category) qs.set('category', params.category)
  if (params.source) qs.set('source', params.source)
  if (params.sort) qs.set('sort', params.sort)
  return apiRequest<InspirationFeedResponse>(`/api/v1/inspirations?${qs}`)
}

export function adminFetchInspirations(params: {
  offset?: number
  limit?: number
  source?: string
} = {}): Promise<InspirationFeedResponse> {
  const qs = new URLSearchParams()
  if (params.offset) qs.set('offset', String(params.offset))
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.source) qs.set('source', params.source)
  return adminApiRequest<InspirationFeedResponse>(`/api/v1/admin/inspirations?${qs}`)
}

export function adminCreateInspiration(formData: FormData): Promise<{ id: string; image_url: string }> {
  return adminApiRequest('/api/v1/admin/inspirations', {
    method: 'POST',
    body: formData,
  })
}

export function adminBatchCreateInspirations(items: Array<{
  title: string
  description?: string | null
  prompt: string
  image_url: string
  external_id?: string | null
  source: string
  source_url?: string | null
  author_name?: string | null
  author_url?: string | null
  language?: string
  categories?: string[] | null
  is_featured?: boolean
}>): Promise<BatchCreateInspirationsResponse> {
  return adminApiRequest('/api/v1/admin/inspirations/batch', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
}

export function adminDeleteInspiration(id: string): Promise<void> {
  return adminApiRequest(`/api/v1/admin/inspirations/${id}`, { method: 'DELETE' })
}
