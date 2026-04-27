import type {
  CreateJobRequest,
  CreateJobResponse,
  GalleryItem,
  JobDetailResponse,
  PublicMetaResponse,
} from './types'

async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
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
    throw new Error(message)
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
    formData.append('aspect_ratio', payload.aspect_ratio)
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
      aspect_ratio: payload.aspect_ratio,
    }),
  })
}

export function fetchJob(jobId: string) {
  return apiRequest<JobDetailResponse>(`/api/v1/jobs/${jobId}`)
}

export function fetchGallery() {
  return apiRequest<GalleryItem[]>('/api/v1/gallery')
}
