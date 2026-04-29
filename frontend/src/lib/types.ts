export type JobStatus = 'queued' | 'processing' | 'succeeded' | 'failed'

export interface PublicModel {
  id: string
  label: string
  enabled: boolean
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
}

export type ImageAspectRatio = 'auto' | '1:1' | '3:4' | '9:16' | '4:3' | '16:9'
export type ImageSize =
  | 'auto'
  | '1024x1024'
  | '1536x1024'
  | '1024x1536'
  | '2048x2048'
  | '2048x1152'
  | '1152x2048'
  | '3840x2160'
  | '2160x3840'
