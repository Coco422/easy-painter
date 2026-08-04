import { isStableSemver, parseReleaseItems, type ReleaseInfo } from '@/lib/release'

export const APP_VERSION = __APP_VERSION__ || 'dev'
export const APP_RELEASES: ReleaseInfo[] = __APP_RELEASES__ || []
export const REPOSITORY_URL = 'https://github.com/Coco422/easy-painter'

const LATEST_RELEASE_API_URL = 'https://api.github.com/repos/Coco422/easy-painter/releases/latest'

interface GitHubLatestReleaseResponse {
  tag_name?: unknown
  body?: unknown
  html_url?: unknown
  published_at?: unknown
  draft?: unknown
  prerelease?: unknown
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
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  })

  if (response.status === 404) return { status: 'none' }
  if (!response.ok) throw new Error(`GitHub release request failed with ${response.status}`)

  const payload = await response.json() as GitHubLatestReleaseResponse
  if (payload.draft === true || payload.prerelease === true) return { status: 'none' }

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
