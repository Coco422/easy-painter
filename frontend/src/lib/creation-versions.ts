import type { CreateJobRequest } from './types.ts'
import { groupJobs } from './job-batches.ts'

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

export function creationVersionRows<T extends { job_id: string; created_at: string }>(jobs: T[], parents: CreationHistory['parents'], membership: Record<string, string> = {}) {
  const ordered = [...jobs].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.job_id.localeCompare(b.job_id))
  function rootOf(id: string) {
    const seen = new Set([id])
    while (parents[id] && !seen.has(parents[id]!)) {
      id = parents[id]!
      seen.add(id)
    }
    return id
  }
  const roots = new Map(ordered.map(job => [job.job_id, rootOf(job.job_id)]))
  const candidates = [...new Set(roots.values())].map(job_id => ({ job_id }))
  const batches = groupJobs(candidates, membership)
  // Preserve acceptance order while queued timestamps are replaced by server timestamps.
  const acceptedOrder = new Map(Object.keys(membership).map((id, index) => [id, index]))
  for (const batch of batches) batch.jobs.sort((a, b) => (acceptedOrder.get(a.job_id) ?? Number.MAX_SAFE_INTEGER) - (acceptedOrder.get(b.job_id) ?? Number.MAX_SAFE_INTEGER))
  const locations = new Map(batches.flatMap((batch, batchIndex) => batch.jobs.map((candidate, candidateIndex) => [candidate.job_id, {
    batchId: batch.id, batchNumber: batchIndex + 1, candidateNumber: candidateIndex + 1,
  }] as const)))
  // Number edits within their own candidate tree. Parallel draws never advance versions.
  const counts = new Map<string, number>()
  const numbers = new Map(ordered.map(job => {
    const root = roots.get(job.job_id)!
    const number = (counts.get(root) ?? 0) + 1
    counts.set(root, number)
    return [job.job_id, number] as const
  }))
  return ordered.map(job => {
    const rootId = roots.get(job.job_id)!
    const location = locations.get(rootId)!
    const parentId = parents[job.job_id] ?? null
    const number = numbers.get(job.job_id)!
    const candidateLabel = `候选图 ${location.candidateNumber}`
    return { job, rootId, ...location, candidateLabel, number, parentId, parentNumber: numbers.get(parentId ?? ''),
      label: parentId ? `${candidateLabel} · V${number}` : candidateLabel }
  })
}

/** Revisions follow their root candidate, even though each edit is a separate paid submission. */
export function creationResultBatches<T extends { job_id: string; created_at: string }>(rows: ReturnType<typeof creationVersionRows<T>>) {
  const batches = new Map<string, { id: string; number: number; candidates: { id: string; label: string; job: T; rows: typeof rows }[] }>()
  for (const row of rows) {
    let batch = batches.get(row.batchId)
    if (!batch) {
      batch = { id: row.batchId, number: row.batchNumber, candidates: [] }
      batches.set(row.batchId, batch)
    }
    let candidate = batch.candidates.find(item => item.id === row.rootId)
    if (!candidate) {
      candidate = { id: row.rootId, label: row.candidateLabel, job: row.job, rows: [] }
      batch.candidates.push(candidate)
    }
    candidate.rows.push(row)
  }
  return [...batches.values()].map(batch => ({ ...batch, candidates: batch.candidates.sort((a, b) => a.rows[0]!.candidateNumber - b.rows[0]!.candidateNumber) }))
}
