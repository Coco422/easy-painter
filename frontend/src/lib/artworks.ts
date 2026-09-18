import { apiRequest, adminApiRequest } from './api'

export type ArtworkKind = 'job' | 'inspiration'
export interface Artwork {
  kind: ArtworkKind
  id: string
  job_id: string | null
  inspiration_id: string | null
  favorite_id: string | null
  title: string
  prompt: string
  revised_prompt: string | null
  is_prompt_public: boolean
  can_view_prompt: boolean
  username: string | null
  is_owner: boolean
  is_in_gallery: boolean
  gallery_visible: boolean
  is_favorite: boolean
  tags: string[]
  status: string | null
  model: string
  size: string
  aspect_ratio: string
  created_at: string | null
  finished_at: string | null
  favorited_at: string | null
  credit_cost: number | null
  billing_status: string | null
  error_message: string | null
  media_state: string
  media_expires_at: string | null
  original_expires_at: string | null
  retention_kind: string
  image_url: string | null
  thumbnail_url: string | null
  submission_status: string
  review_reason: string | null
}
export interface ArtworkPage {
  items: Artwork[]
  total: number
  page: number
  page_size: number
  server_time: string
}
export interface Submission extends Artwork {
  submitted_at: string
  reviewed_at: string | null
}

export function fetchArtworkPage(path: string, params: Record<string, string | number>, signal?: AbortSignal) {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
  return apiRequest<ArtworkPage>(`/api/v1/${path}?${query}`, { signal, cache: 'no-store' })
}
export function fetchArtwork(kind: ArtworkKind, id: string) {
  return apiRequest<Artwork>(`/api/v1/artworks/${kind}/${encodeURIComponent(id)}`, { cache: 'no-store' })
}
export async function setFavorite(item: Artwork, favorite: boolean) {
  await apiRequest(`/api/v1/favorites/${item.kind}/${encodeURIComponent(item.id)}`, { method: favorite ? 'PUT' : 'DELETE' })
  return fetchArtwork(item.kind, item.id)
}
export function clearInvalidFavorites() {
  return apiRequest<{ removed: number }>('/api/v1/favorites/unavailable', { method: 'DELETE' })
}
export function setGallery(item: Artwork, joined: boolean, tags: string[] = [], isPromptPublic = true) {
  return apiRequest<Artwork>(`/api/v1/jobs/${encodeURIComponent(item.id)}/gallery`, {
    method: joined ? 'PUT' : 'DELETE',
    body: joined ? JSON.stringify({ tags, is_prompt_public: isPromptPublic }) : undefined,
  })
}
export function submitCommunity(item: Artwork) {
  return apiRequest<Artwork>(`/api/v1/jobs/${encodeURIComponent(item.id)}/community-submission`, {
    method: 'POST', body: JSON.stringify({ consent_public_prompt: true }),
  })
}
export function withdrawCommunity(item: Artwork) {
  return apiRequest<Artwork>(`/api/v1/jobs/${encodeURIComponent(item.id)}/community-submission`, { method: 'DELETE' })
}
export function fetchSubmissions(state: string, page: number) {
  return adminApiRequest<Omit<ArtworkPage, 'items'> & { items: Submission[] }>(`/api/v1/admin/community-submissions?state=${state}&page=${page}&page_size=25`)
}
export function reviewSubmission(id: string, decision: 'approve' | 'reject', reason = '') {
  return adminApiRequest(`/api/v1/admin/community-submissions/${encodeURIComponent(id)}`, {
    method: 'PUT', body: JSON.stringify({ decision, reason }),
  })
}
