import {
  assetIds,
  clone,
  IMAGE_TYPES,
  MAX_IMAGE_BYTES,
  MAX_PROJECT_BYTES,
  uid,
  validateProject,
} from './model'
import type { CanvasAsset, CanvasProject } from './model'
import { sha256Hex } from '../browser-crypto'
const DB_NAME = 'easy-painter-canvas'
let opening: Promise<IDBDatabase> | undefined
function database() {
  if (!opening)
    opening = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1)
      request.onupgradeneeded = () => {
        request.result.createObjectStore('projects', {
          keyPath: ['ownerId', 'id'],
        })
        request.result.createObjectStore('assets', {
          keyPath: ['ownerId', 'id'],
        })
      }
      request.onsuccess = () => {
        request.result.onversionchange = () => {
          request.result.close()
          opening = undefined
        }
        resolve(request.result)
      }
      request.onerror = () => {
        opening = undefined
        reject(new Error('浏览器本地存储无法打开。请检查浏览器设置。'))
      }
      request.onblocked = () => {
        opening = undefined
        reject(new Error('请关闭其他画布标签页后重试。'))
      }
    })
  return opening
}
function result<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}
export async function listProjects(ownerId: string): Promise<CanvasProject[]> {
  const db = await database()
  return (
    await result(
      db
        .transaction('projects')
        .objectStore('projects')
        .getAll(IDBKeyRange.bound([ownerId, ''], [ownerId, '\uffff'])),
    )
  ).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}
export async function getProject(
  ownerId: string,
  id: string,
): Promise<CanvasProject | undefined> {
  return result(
    (await database())
      .transaction('projects')
      .objectStore('projects')
      .get([ownerId, id]),
  )
}
export async function getAsset(
  ownerId: string,
  id: string,
): Promise<CanvasAsset> {
  const asset = await result(
    (await database())
      .transaction('assets')
      .objectStore('assets')
      .get([ownerId, id]),
  )
  if (!asset) throw new Error('本地素材缺失，请从完整项目文件或云端恢复。')
  return asset
}
export async function saveProject(
  project: CanvasProject,
  assets: CanvasAsset[] = [],
): Promise<number> {
  const snapshot = validateProject(project, project.ownerId),
    db = await database()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['projects', 'assets'], 'readwrite')
    let failure: Error | undefined
    const projects = tx.objectStore('projects'),
      request = projects.get([project.ownerId, project.id])
    request.onsuccess = () => {
      if ((request.result?.revision ?? 0) !== project.revision) {
        failure = new Error(
          '此画布已在其他标签页更新或移除。请先导出当前内容，再重新打开画布。',
        )
        tx.abort()
        return
      }
      snapshot.revision += 1
      for (const a of assets) {
        if (a.ownerId !== project.ownerId) {
          failure = new Error('素材所属账号不匹配。')
          tx.abort()
          return
        }
        tx.objectStore('assets').put(a)
      }
      projects.put(snapshot)
    }
    tx.oncomplete = () => resolve(snapshot.revision)
    tx.onabort = tx.onerror = () =>
      reject(
        failure ??
          new Error(
            tx.error?.name === 'QuotaExceededError'
              ? '浏览器存储空间不足，尚未保存。请导出项目或清理浏览器空间。'
              : '本地保存失败，请导出备份后重试。',
          ),
      )
  })
}
export async function deleteProject(ownerId: string, id: string) {
  const db = await database()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(['projects', 'assets'], 'readwrite'),
      projects = tx.objectStore('projects')
    projects.delete([ownerId, id])
    const request = projects.getAll(
      IDBKeyRange.bound([ownerId, ''], [ownerId, '\uffff']),
    )
    request.onsuccess = () => {
      const retained = new Set(
        (request.result as CanvasProject[]).flatMap(assetIds),
      )
      const cursor = tx
        .objectStore('assets')
        .openCursor(IDBKeyRange.bound([ownerId, ''], [ownerId, '\uffff']))
      cursor.onsuccess = () => {
        if (cursor.result) {
          if (!retained.has(cursor.result.value.id)) cursor.result.delete()
          cursor.result.continue()
        }
      }
    }
    tx.oncomplete = () => resolve()
    tx.onabort = tx.onerror = () => reject(new Error('删除本地画布失败。'))
  })
}
export async function makeAsset(
  ownerId: string,
  blob: Blob,
  name: string,
): Promise<CanvasAsset> {
  if (
    !IMAGE_TYPES.includes(blob.type) ||
    blob.size > MAX_IMAGE_BYTES ||
    !blob.size
  )
    throw new Error('请选择不超过 12 MB 的 PNG、JPEG 或 WebP 图片。')
  const bitmap = await createImageBitmap(blob)
  const pixels = bitmap.width * bitmap.height
  bitmap.close()
  if (pixels > 40_000_000) throw new Error('图片像素过大，请缩小后导入。')
  return {
    id: await sha256Hex(await blob.arrayBuffer()),
    ownerId,
    name: name.slice(0, 120),
    blob,
  }
}
function dataURL(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}
export async function exportProject(
  project: CanvasProject,
  pending: Map<string, CanvasAsset> = new Map(),
) {
  const assets = await Promise.all(
    assetIds(project).map(async (id) => {
      const a = pending.get(id) ?? (await getAsset(project.ownerId, id))
      return { id, name: a.name, data: await dataURL(a.blob) }
    }),
  )
  const portable = clone(project)
  portable.cloudEnabled = false
  portable.cloudVersion = null
  return new Blob(
    [
      JSON.stringify({
        format: 'easy-painter-canvas',
        version: 1,
        project: portable,
        assets,
      }),
    ],
    { type: 'application/json' },
  )
}
export async function importProject(file: File, ownerId: string) {
  if (file.size > MAX_PROJECT_BYTES * 1.4)
    throw new Error('项目文件超过 180 MB，请拆分项目。')
  const raw = JSON.parse(await file.text())
  if (
    raw?.format !== 'easy-painter-canvas' ||
    raw.version !== 1 ||
    !Array.isArray(raw.assets) ||
    raw.assets.length > 1000
  )
    throw new Error('请选择 Easy Painter 导出的完整画布文件。')
  const project = validateProject(raw.project, ownerId)
  project.id = uid()
  project.revision = 0
  project.cloudEnabled = false
  project.cloudVersion = null
  project.title = `${project.title.slice(0, 110)}（导入）`
  project.updatedAt = new Date().toISOString()
  const assets: CanvasAsset[] = [],
    seen = new Set<string>()
  let bytes = 0
  for (const entry of raw.assets) {
    if (
      typeof entry.data !== 'string' ||
      !/^data:image\/(png|jpeg|webp);base64,/.test(entry.data) ||
      typeof entry.name !== 'string'
    )
      throw new Error('项目中包含不支持的素材。')
    const [head, encoded] = entry.data.split(',')
    if (!encoded || encoded.length > MAX_IMAGE_BYTES * 1.4)
      throw new Error('项目素材过大。')
    const binary = atob(encoded),
      blob = new Blob([Uint8Array.from(binary, (c) => c.charCodeAt(0))], {
        type: head.slice(5, head.indexOf(';')),
      })
    bytes += blob.size
    if (bytes > MAX_PROJECT_BYTES) throw new Error('项目素材总量超过 128 MB。')
    const asset = await makeAsset(ownerId, blob, entry.name)
    if (asset.id !== entry.id || seen.has(asset.id))
      throw new Error('素材校验失败或存在重复条目。')
    seen.add(asset.id)
    assets.push(asset)
  }
  if (assetIds(project).some((id) => !seen.has(id)))
    throw new Error('项目文件缺少引用的素材。')
  // Imports never automatically submit generation requests; only known jobs may resume polling.
  for (const run of project.runs)
    if (!run.jobId && !['succeeded', 'failed'].includes(run.status)) {
      run.status = 'failed'
      run.error = '导入的未提交任务不会自动执行，请创建新的生成任务。'
    }
  project.revision = await saveProject(project, assets)
  return project
}
export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob),
    a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
