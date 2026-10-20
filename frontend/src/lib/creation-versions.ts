import type { CreateJobRequest } from './types.ts'

export interface PendingRevision {
  key: string
  parentId: string
  request: CreateJobRequest
}
export interface CreationHistory {
  parents: Record<string, string | null>
  pending: PendingRevision | null
}
export const MAX_CREATION_VERSIONS = 100
export const creationHistoryKey = (ownerId: string) => `easy-painter:creation-versions:${ownerId}`
export const emptyCreationHistory = (): CreationHistory => ({ parents: {}, pending: null })
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[\w-]{1,128}$/.test(value)

export function parseCreationHistory(raw: string | null): CreationHistory {
  try {
    const data = JSON.parse(raw ?? '{}')
    const parents = Object.fromEntries(Object.entries(data?.parents ?? {}).filter(([id, parent]) => identifier(id) && (parent === null || (identifier(parent) && parent !== id))).slice(-MAX_CREATION_VERSIONS)) as CreationHistory['parents']
    // Corrupt or manually edited data must never create cyclic ancestry.
    for (const id of Object.keys(parents)) {
      const seen = new Set([id])
      let next = parents[id]
      while (next) {
        if (seen.has(next)) { parents[id] = null; break }
        seen.add(next)
        next = parents[next]
      }
    }
    const pending = data?.pending as PendingRevision | undefined
    const request = pending?.request
    const valid = pending && identifier(pending.key) && identifier(pending.parentId) && request &&
      typeof request.prompt === 'string' && request.prompt.length > 0 && request.prompt.length <= 20000 &&
      typeof request.model === 'string' && request.model.length <= 128 && typeof request.size === 'string' && request.size.length <= 32 &&
      Array.isArray(request.reference_image_ids) && request.reference_image_ids.length === 1 && request.reference_image_ids.every(identifier)
    return { parents, pending: valid ? pending : null }
  } catch { return emptyCreationHistory() }
}

export function creationVersionRows<T extends { job_id: string; created_at: string }>(jobs: T[], parents: CreationHistory['parents']) {
  const ordered = [...jobs].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.job_id.localeCompare(b.job_id))
  const numbers = new Map(ordered.map((job, index) => [job.job_id, index + 1]))
  return ordered.map(job => ({ job, number: numbers.get(job.job_id)!, parentId: parents[job.job_id] ?? null, parentNumber: numbers.get(parents[job.job_id] ?? '') }))
}
