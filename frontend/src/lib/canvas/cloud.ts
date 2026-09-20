import { apiRequest } from '@/lib/api'
import { getAuthHeader } from '@/lib/auth'
import { assetIds, clone, uid, validateProject } from './model'
import type { CanvasProject } from './model'
import { getAsset, getProject, makeAsset, saveProject } from './storage'
export interface CloudCapabilities {
  can_write: boolean
  max_projects: number
  max_bytes: number
  used_bytes: number
}
export interface CloudProject {
  id: string
  title: string
  version: number
  updated_at: string
  bytes: number
}
interface CloudDetail extends CloudProject {
  document: CanvasProject | null
  asset_ids: string[]
}
export const cloudCapabilities = () =>
  apiRequest<CloudCapabilities>('/api/v1/canvas/capabilities')
export const cloudProjects = () =>
  apiRequest<CloudProject[]>('/api/v1/canvas/projects')
export const deleteCloudProject = (id: string) =>
  apiRequest<void>(`/api/v1/canvas/projects/${id}`, { method: 'DELETE' })
export async function syncProject(
  project: CanvasProject,
  assertOwner: () => void,
): Promise<number> {
  assertOwner()
  const remote = await apiRequest<CloudDetail>('/api/v1/canvas/projects', {
    method: 'POST',
    body: JSON.stringify({ id: project.id, title: project.title }),
  })
  assertOwner()
  if (remote.version !== (project.cloudVersion ?? 0))
    throw new Error(
      '云端已有其他版本。请先从画布列表恢复云端副本，对比后再保存。',
    )
  const existing = new Set(remote.asset_ids)
  for (const id of assetIds(project)) {
    assertOwner()
    if (existing.has(id)) continue
    const asset = await getAsset(project.ownerId, id)
    assertOwner()
    const form = new FormData()
    form.append('file', asset.blob, asset.name)
    await apiRequest(`/api/v1/canvas/projects/${project.id}/assets/${id}`, {
      method: 'PUT',
      body: form,
    })
    assertOwner()
  }
  const saved = await apiRequest<CloudDetail>(
    `/api/v1/canvas/projects/${project.id}`,
    {
      method: 'PUT',
      body: JSON.stringify({
        expected_version: project.cloudVersion ?? 0,
        document: project,
      }),
    },
  )
  assertOwner()
  return saved.version
}
export async function restoreCloudProject(
  id: string,
  ownerId: string,
  assertOwner: () => void,
) {
  const remote = await apiRequest<CloudDetail>(`/api/v1/canvas/projects/${id}`)
  assertOwner()
  if (!remote.document)
    throw new Error('此云端画布还没有完成首次保存。请在原设备重试同步。')
  const project = validateProject(remote.document, ownerId),
    assets = []
  for (const hash of assetIds(project)) {
    assertOwner()
    try {
      assets.push(await getAsset(ownerId, hash))
      continue
    } catch {
      /* Download missing assets. */
    }
    const response = await fetch(
      `/api/v1/canvas/projects/${id}/assets/${hash}`,
      { headers: getAuthHeader() },
    )
    if (!response.ok) throw new Error('云端素材读取失败，本地画布尚未改变。')
    const asset = await makeAsset(
      ownerId,
      await response.blob(),
      `${hash.slice(0, 8)}.png`,
    )
    assertOwner()
    if (asset.id !== hash) throw new Error('云端素材校验失败。')
    assets.push(asset)
  }
  if (await getProject(ownerId, id)) {
    project.id = uid()
    project.title = `${project.title.slice(0, 100)}（云端副本）`
    project.cloudVersion = null
    project.cloudEnabled = false
  } else {
    project.cloudVersion = remote.version
    project.cloudEnabled = false
  }
  project.revision = 0
  project.updatedAt = new Date().toISOString()
  assertOwner()
  project.revision = await saveProject(project, assets)
  return project
}
