import { isStableSemver, parseReleaseItems, type ReleaseInfo } from '@/lib/release'

export const APP_VERSION = __APP_VERSION__ || 'dev'
export const APP_RELEASES: ReleaseInfo[] = __APP_RELEASES__ || []
export const REPOSITORY_URL = 'https://github.com/Coco422/easy-painter'

const LATEST_RELEASE_API_URL = '/api/v1/meta/releases/latest'

interface GitHubLatestReleaseResponse {
  tag_name?: unknown
  body?: unknown
  html_url?: unknown
  published_at?: unknown
  draft?: unknown
  prerelease?: unknown
}

interface LatestReleaseApiResponse {
  status?: unknown
  release?: unknown
}

export interface RemoteReleaseInfo extends ReleaseInfo {
  url: string
  hasFormattedNotes: boolean
}

export type LatestReleaseResult =
  | { status: 'found'; release: RemoteReleaseInfo }
  | { status: 'none' }

export async function fetchLatestGitHubRelease(signal?: AbortSignal): Promise<LatestReleaseResult> {
  const response = await fetch(LATEST_RELEASE_API_URL, {
    signal,
  })

  if (!response.ok) throw new Error(`Release request failed with ${response.status}`)

  const result = await response.json() as LatestReleaseApiResponse
  if (result.status === 'none') return { status: 'none' }
  if (result.status !== 'found' || !result.release || typeof result.release !== 'object') {
    throw new Error('Release response is invalid')
  }
  const payload = result.release as GitHubLatestReleaseResponse

  const version = typeof payload.tag_name === 'string' ? payload.tag_name.trim() : ''
  const url = typeof payload.html_url === 'string' ? payload.html_url : ''
  if (!isStableSemver(version) || !url.startsWith(`${REPOSITORY_URL}/releases/tag/`)) {
    throw new Error('GitHub release response is invalid')
  }

  const body = typeof payload.body === 'string' ? payload.body : ''
  const items = parseReleaseItems(body)
  const publishedAt = typeof payload.published_at === 'string' ? payload.published_at : ''

  return {
    status: 'found',
    release: {
      version,
      date: /^\d{4}-\d{2}-\d{2}/.test(publishedAt) ? publishedAt.slice(0, 10) : '',
      items,
      url,
      hasFormattedNotes: items.length > 0,
    },
  }
}
