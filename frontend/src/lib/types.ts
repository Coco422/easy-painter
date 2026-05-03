export type JobStatus = 'queued' | 'processing' | 'succeeded' | 'failed'

export interface PublicModel {
  id: string
  label: string
  enabled: boolean
  supports_reference_image: boolean
  supported_sizes: string[]
}

export interface PublicMetaResponse {
  site_name: string
  prompt_max_length: number
  polling_interval_ms: number
  example_prompts: string[]
  models: PublicModel[]
}

export interface CreateJobRequest {
  prompt: string
  model: string
  size: ImageSize
  reference_image?: File | null
}

export interface CreateJobResponse {
  job_id: string
  status: JobStatus
  poll_url: string
  rate_limit_remaining: number
}

export interface JobDetailResponse {
  job_id: string
  status: JobStatus
  image_url: string | null
  prompt: string
  revised_prompt: string | null
  model: string
  size: string
  aspect_ratio?: ImageAspectRatio | null
  error_message: string | null
  created_at: string
  finished_at: string | null
}

export interface GalleryItem {
  job_id: string
  image_url: string
  prompt: string
  revised_prompt: string | null
  model: string
  size: string
  aspect_ratio?: ImageAspectRatio | null
  finished_at: string
  username?: string | null
  is_public?: boolean
  is_favorite?: boolean
  like_count?: number
  liked_by_me?: boolean
}

export type ImageAspectRatio = 'auto' | '1:1' | '3:4' | '9:16' | '4:3' | '16:9'
export type ImageSize =
  | 'auto'
  | '1024x1024'
  | '1280x720'
  | '720x1280'
  | '1792x1024'
  | '1024x1792'
  | '1536x1024'
  | '1024x1536'
  | '2048x2048'
  | '2048x1152'
  | '1152x2048'
  | '3840x2160'
  | '2160x3840'

export type BatchCount = 1 | 2 | 4

export interface UserInfo {
  id: string
  username: string
  display_name: string
  is_public: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface AdminJobItem {
  job_id: string
  status: string
  prompt: string
  revised_prompt: string | null
  model: string
  size: string
  aspect_ratio: string
  username: string | null
  error_message: string | null
  provider_job_meta: Record<string, unknown> | null
  image_url: string | null
  reference_image_filename: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface UpstreamProvider {
  id: string
  name: string
  base_url: string
  api_key: string
  timeout_seconds: number
  default_size: string
  default_quality: string
  default_output_format: string
  default_output_compression: number
  default_background: string
  default_moderation: string
}

export interface ModelConfig {
  id: string
  provider_id: string
  label: string
  enabled: boolean
  supports_reference_image: boolean
  supported_sizes: string[]
  sort_order: number
}
