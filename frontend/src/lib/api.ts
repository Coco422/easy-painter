import { getAdminAuthHeader, getAuthHeader } from './auth'
import type {
  AdminHealth,
  AdminInspirationItem,
  AdminJobPage,
  AdminOverview,
  AnnouncementItem,
  BatchCreateInspirationsResponse,
  CreateJobRequest,
  CreateJobResponse,
  CreditTransactionItem,
  GalleryItem,
  GalleryPageResponse,
  InspirationFeedResponse,
  JobDetailResponse,
  ModelConfig,
  PageResponse,
  PublicMetaResponse,
  RedemptionCodeItem,
  ReferenceImageItem,
  UpstreamProvider,
  UserGroup,
  UserInfo,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: Record<string, unknown>,
    readonly retryAfter?: number,
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
    const retryAfterHeader = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
    throw new ApiError(
      message,
      response.status,
      detail,
      Number.isFinite(retryAfterHeader) && retryAfterHeader > 0 ? retryAfterHeader : undefined,
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function fetchPublicMeta() {
  return apiRequest<PublicMetaResponse>('/api/v1/meta/public')
}

export function fetchAnnouncements() {
  return apiRequest<AnnouncementItem[]>('/api/v1/announcements')
}

export function createJob(payload: CreateJobRequest, idempotencyKey: string) {
  const body: Record<string, unknown> = {
    prompt: payload.prompt,
    model: payload.model,
    size: payload.size,
  }
  if (payload.reference_image_id) {
    body.reference_image_id = payload.reference_image_id
  }
  return apiRequest<CreateJobResponse>('/api/v1/jobs', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(body),
  })
}

// ---- Reference Image APIs ----

export function uploadReferenceImage(file: File, confirmEvictOldest = false) {
  const formData = new FormData()
  formData.append('file', file)
  if (confirmEvictOldest) formData.append('confirm_evict_oldest', 'true')
  return apiRequest<ReferenceImageItem>('/api/v1/reference-images', {
    method: 'POST',
    body: formData,
  })
}

export function fetchReferenceImages(page = 1, pageSize = 50) {
  return apiRequest<PageResponse<ReferenceImageItem>>(`/api/v1/reference-images?page=${page}&page_size=${pageSize}`)
}

export function deleteReferenceImage(id: string) {
  return apiRequest<void>(`/api/v1/reference-images/${id}`, { method: 'DELETE' })
}

export async function fetchReferenceImageObjectUrl(id: string): Promise<string> {
  const response = await fetch(`/api/v1/reference-images/${id}/file`, {
    headers: getAuthHeader(),
  })
  if (!response.ok) {
    throw new ApiError('参考图加载失败，请稍后重试。', response.status)
  }
  const blob = await response.blob()
  return URL.createObjectURL(blob)
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
  page?: number
  page_size?: number
} = {}) {
  const qs = new URLSearchParams()
  if (params.sort) qs.set('sort', params.sort)
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  return apiRequest<GalleryPageResponse>(`/api/v1/gallery/public?${qs}`)
}

export function deleteJob(jobId: string) {
  return apiRequest<void>(`/api/v1/jobs/${jobId}`, { method: 'DELETE' })
}

export function toggleJobPublic(jobId: string, tags?: string[], isPromptPublic?: boolean) {
  return apiRequest<{ is_public: boolean }>(`/api/v1/jobs/${jobId}/public`, {
    method: 'PUT',
    body: JSON.stringify({
      tags: tags ?? null,
      is_prompt_public: isPromptPublic ?? true,
    }),
  })
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

export function fetchPopularTags(limit = 20) {
  return apiRequest<string[]>(`/api/v1/tags/popular?limit=${limit}`)
}

export function fetchUserGallery(username: string, page = 1, pageSize = 20) {
  return apiRequest<GalleryPageResponse>(`/api/v1/gallery/${username}?page=${page}&page_size=${pageSize}`)
}

export function updateProfile(data: { display_name?: string; is_public?: boolean }) {
  return apiRequest<UserInfo>('/api/v1/users/me', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export function requestBindEmailCode(email: string) {
  return apiRequest<{ message: string; expires_in: number; retry_after: number }>('/api/v1/users/me/email/code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function bindEmail(email: string, emailCode: string) {
  return apiRequest<UserInfo>('/api/v1/users/me/email', {
    method: 'PUT',
    body: JSON.stringify({ email, email_code: emailCode }),
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
    const retryAfterHeader = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
    throw new ApiError(
      message,
      response.status,
      undefined,
      Number.isFinite(retryAfterHeader) && retryAfterHeader > 0 ? retryAfterHeader : undefined,
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}


export function adminDeleteJob(jobId: string) {
  return adminApiRequest<void>(`/api/v1/admin/jobs/${jobId}`, { method: 'DELETE' })
}

export function adminFetchJobs(options: { status?: string; page?: number; pageSize?: number } = {}) {
  const params = new URLSearchParams()
  if (options.status) params.set('status', options.status)
  params.set('page', String(options.page ?? 1))
  params.set('page_size', String(options.pageSize ?? 50))
  return adminApiRequest<AdminJobPage>(`/api/v1/admin/jobs?${params.toString()}`)
}

export function adminBatchDeleteJobs(jobIds: string[]) {
  return adminApiRequest<{ deleted: number; failed: string[] }>('/api/v1/admin/jobs/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ job_ids: jobIds }),
  })
}

export function adminFetchUsers(options: { page?: number; pageSize?: number; q?: string; groupCode?: string } = {}) {
  const params = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 50),
  })
  if (options.q) params.set('q', options.q)
  if (options.groupCode) params.set('group_code', options.groupCode)
  return adminApiRequest<PageResponse<UserInfo>>(`/api/v1/admin/users?${params}`)
}

export function adminCreateUser(data: { username: string; email?: string; password: string; display_name?: string; group_code?: string }) {
  return adminApiRequest<UserInfo>('/api/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminUpdateUser(userId: string, data: { email?: string | null; password?: string; display_name?: string; is_public?: boolean; group_code?: string }) {
  return adminApiRequest<UserInfo>(`/api/v1/admin/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

// ---- Admin User Group APIs ----

export function adminFetchUserGroups() {
  return adminApiRequest<UserGroup[]>('/api/v1/admin/user-groups')
}

export function adminCreateUserGroup(data: Omit<UserGroup, 'created_at' | 'updated_at' | 'user_count'>) {
  return adminApiRequest<UserGroup>('/api/v1/admin/user-groups', { method: 'POST', body: JSON.stringify(data) })
}

export function adminUpdateUserGroup(code: string, data: Partial<Omit<UserGroup, 'code' | 'created_at' | 'updated_at' | 'user_count'>>) {
  return adminApiRequest<UserGroup>(`/api/v1/admin/user-groups/${encodeURIComponent(code)}`, { method: 'PUT', body: JSON.stringify(data) })
}

export function adminDeleteUserGroup(code: string) {
  return adminApiRequest<void>(`/api/v1/admin/user-groups/${encodeURIComponent(code)}`, { method: 'DELETE' })
}

export function adminDeleteUser(userId: string) {
  return adminApiRequest<void>(`/api/v1/admin/users/${userId}`, { method: 'DELETE' })
}

// ---- Admin Announcement APIs ----

export function adminFetchAnnouncements(page = 1, pageSize = 50) {
  return adminApiRequest<PageResponse<AnnouncementItem>>(`/api/v1/admin/announcements?page=${page}&page_size=${pageSize}`)
}

export function adminCreateAnnouncement(data: {
  title: string
  content: string
  level: AnnouncementItem['level']
  audience: AnnouncementItem['audience']
  enabled: boolean
}) {
  return adminApiRequest<AnnouncementItem>('/api/v1/admin/announcements', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminUpdateAnnouncement(id: string, data: Partial<Pick<AnnouncementItem, 'title' | 'content' | 'level' | 'audience' | 'enabled'>>) {
  return adminApiRequest<AnnouncementItem>(`/api/v1/admin/announcements/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export function adminDeleteAnnouncement(id: string) {
  return adminApiRequest<void>(`/api/v1/admin/announcements/${id}`, { method: 'DELETE' })
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

export function adminFetchCodes(statusFilter: 'all' | 'unused' | 'used' = 'all', page = 1, pageSize = 50) {
  return adminApiRequest<PageResponse<RedemptionCodeItem>>(
    `/api/v1/admin/codes?status=${statusFilter}&page=${page}&page_size=${pageSize}`,
  )
}

export function adminAdjustCredits(userId: string, data: { amount: number; reason?: string }) {
  return adminApiRequest<{ credits: number; requested_amount: number; applied_amount: number }>(`/api/v1/admin/users/${userId}/credits`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function adminFetchOverview(window: '24h' | '7d' | '30d' = '24h') {
  return adminApiRequest<AdminOverview>(`/api/v1/admin/overview?window=${window}`)
}

export function adminFetchHealth() {
  return adminApiRequest<AdminHealth>('/api/v1/admin/health')
}

export function adminFetchTransactions(userId?: string, page = 1, pageSize = 50) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (userId) params.set('user_id', userId)
  return adminApiRequest<PageResponse<CreditTransactionItem & { id: string; user_id: string; username: string | null }>>(
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

export function fetchInspirationCategories(limit = 20) {
  return apiRequest<string[]>(`/api/v1/inspirations/categories?limit=${limit}`)
}

export function adminFetchInspirations(params: {
  page?: number
  pageSize?: number
  source?: string
} = {}): Promise<PageResponse<AdminInspirationItem>> {
  const qs = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
  })
  if (params.source) qs.set('source', params.source)
  return adminApiRequest<PageResponse<AdminInspirationItem>>(`/api/v1/admin/inspirations?${qs}`)
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

export function adminFetchInspirationCandidates(params: { page?: number; pageSize?: number } = {}) {
  const qs = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
  })
  return adminApiRequest<PageResponse<import('./types').AdminInspirationCandidate>>(`/api/v1/admin/inspirations/candidates?${qs}`)
}

export function adminCreateInspirationFromJob(jobId: string) {
  return adminApiRequest<import('./types').AdminInspirationItem>(`/api/v1/admin/inspirations/from-job/${encodeURIComponent(jobId)}`, { method: 'POST' })
}

export function adminUpdateInspiration(id: string, data: Partial<import('./types').InspirationItem>) {
  return adminApiRequest<import('./types').AdminInspirationItem>(`/api/v1/admin/inspirations/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) })
}
