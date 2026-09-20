// Interaction model inspired by basketikun/infinite-canvas; see THIRD_PARTY_NOTICES.md.
import { randomId } from '../browser-crypto.ts'
export type Point = { x: number; y: number }
export type Viewport = Point & { scale: number }
export type NodeKind = 'text' | 'image' | 'generation' | 'group'
export interface CanvasNode extends Point {
  id: string
  type: NodeKind
  title: string
  width: number
  height: number
  text?: string
  assetId?: string
  groupId?: string
  prompt?: string
  model?: string
  size?: string
  count?: number
}
export interface CanvasEdge {
  id: string
  from: string
  to: string
}
export interface CanvasRun {
  id: string
  nodeId: string
  sourceId: string
  prompt: string
  model: string
  size: string
  referenceIds: string[]
  uploadedIds: string[]
  jobId?: string
  assetId?: string
  status:
    | 'preparing'
    | 'submitting'
    | 'queued'
    | 'processing'
    | 'succeeded'
    | 'failed'
    | 'unknown'
  error?: string
  mediaError?: string
}
export interface CanvasProject {
  schemaVersion: 1
  id: string
  ownerId: string
  title: string
  updatedAt: string
  revision: number
  cloudVersion: number | null
  cloudEnabled: boolean
  viewport: Viewport
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  runs: CanvasRun[]
}
export interface CanvasAsset {
  id: string
  ownerId: string
  name: string
  blob: Blob
}
export const MAX_NODES = 300
export const MAX_ASSETS = 1000
export const MAX_IMAGE_BYTES = 12 * 1024 * 1024
export const MAX_PROJECT_BYTES = 128 * 1024 * 1024
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))
export const uid = randomId
export function newProject(
  ownerId: string,
  title = '未命名画布',
): CanvasProject {
  return {
    schemaVersion: 1,
    id: uid(),
    ownerId,
    title,
    updatedAt: new Date().toISOString(),
    revision: 0,
    cloudVersion: null,
    cloudEnabled: false,
    viewport: { x: 80, y: 70, scale: 1 },
    nodes: [],
    edges: [],
    runs: [],
  }
}
export function newNode(type: NodeKind, point: Point): CanvasNode {
  return {
    id: uid(),
    type,
    ...point,
    title: {
      text: '灵感笔记',
      image: '图片',
      generation: '生成图片',
      group: '素材组',
    }[type],
    width: type === 'generation' ? 320 : 280,
    height: type === 'generation' ? 350 : type === 'text' ? 210 : 260,
    ...(type === 'text' ? { text: '' } : {}),
    ...(type === 'generation'
      ? { prompt: '', model: '', size: 'auto', count: 1 }
      : {}),
  }
}
export function worldPoint(point: Point, viewport: Viewport): Point {
  return {
    x: (point.x - viewport.x) / viewport.scale,
    y: (point.y - viewport.y) / viewport.scale,
  }
}
export function zoomAt(
  viewport: Viewport,
  point: Point,
  scale: number,
): Viewport {
  const next = Math.max(0.1, Math.min(3, scale)),
    world = worldPoint(point, viewport)
  return {
    x: point.x - world.x * next,
    y: point.y - world.y * next,
    scale: next,
  }
}
export function connect(project: CanvasProject, from: string, to: string) {
  const source = project.nodes.find((n) => n.id === from),
    target = project.nodes.find((n) => n.id === to)
  if (
    !source ||
    !target ||
    from === to ||
    target.type !== 'generation' ||
    source.type === 'generation'
  )
    throw new Error('请将图片、文本或素材组连接到生成节点。')
  if (!project.edges.some((e) => e.from === from && e.to === to))
    project.edges.push({ id: uid(), from, to })
}
export function generationInputs(project: CanvasProject, targetId: string) {
  const nodes = project.edges
    .filter((e) => e.to === targetId)
    .flatMap((edge) => {
      const node = project.nodes.find((n) => n.id === edge.from)
      return node?.type === 'group'
        ? project.nodes.filter((n) => n.groupId === node.id)
        : node
          ? [node]
          : []
    })
  const assets = [
    ...new Set(
      nodes.flatMap((n) => {
        const id =
          n.assetId ?? project.runs.find((r) => r.nodeId === n.id)?.assetId
        return id ? [id] : []
      }),
    ),
  ]
  const text = [
    ...new Set(
      nodes
        .filter((n) => n.type === 'text')
        .map((n) => n.text?.trim())
        .filter(Boolean),
    ),
  ].join('\n\n')
  return { assets, text }
}
export function assetIds(project: CanvasProject): string[] {
  return [
    ...new Set([
      ...project.nodes.flatMap((n) => (n.assetId ? [n.assetId] : [])),
      ...project.runs.flatMap((r) => [
        ...r.referenceIds,
        ...(r.assetId ? [r.assetId] : []),
      ]),
    ]),
  ]
}
export function removeNodes(project: CanvasProject, ids: string[]) {
  project.nodes = project.nodes
    .filter((n) => !ids.includes(n.id))
    .map((n) =>
      ids.includes(n.groupId ?? '') ? { ...n, groupId: undefined } : n,
    )
  project.edges = project.edges.filter(
    (e) => !ids.includes(e.from) && !ids.includes(e.to),
  )
}
export function validateProject(raw: unknown, ownerId: string): CanvasProject {
  const p = clone(raw) as CanvasProject
  const finite = (n: unknown, min: number, max: number) =>
    typeof n === 'number' && Number.isFinite(n) && n >= min && n <= max
  const str = (s: unknown, max: number) =>
    typeof s === 'string' && s.length <= max
  const id = (s: unknown) =>
    typeof s === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(s)
  const hash = (s: unknown) => typeof s === 'string' && /^[a-f0-9]{64}$/.test(s)
  if (
    !p ||
    p.schemaVersion !== 1 ||
    !id(p.id) ||
    !str(p.title, 120) ||
    !Array.isArray(p.nodes) ||
    p.nodes.length > MAX_NODES ||
    !Array.isArray(p.edges) ||
    p.edges.length > 1000 ||
    !Array.isArray(p.runs) ||
    p.runs.length > 1000 ||
    !p.viewport
  )
    throw new Error('画布文件格式或版本不受支持。')
  if (
    !finite(p.viewport.x, -1e7, 1e7) ||
    !finite(p.viewport.y, -1e7, 1e7) ||
    !finite(p.viewport.scale, 0.1, 3)
  )
    throw new Error('画布视口数据无效。')
  const ids = new Set<string>()
  for (const n of p.nodes) {
    if (
      !n ||
      !id(n.id) ||
      ids.has(n.id) ||
      !['text', 'image', 'generation', 'group'].includes(n.type) ||
      !str(n.title, 120) ||
      !finite(n.x, -1e7, 1e7) ||
      !finite(n.y, -1e7, 1e7) ||
      !finite(n.width, 80, 10000) ||
      !finite(n.height, 60, 10000) ||
      (n.text !== undefined && !str(n.text, 20000)) ||
      (n.prompt !== undefined && !str(n.prompt, 20000)) ||
      (n.assetId !== undefined && !hash(n.assetId)) ||
      (n.model !== undefined && !str(n.model, 128)) ||
      (n.size !== undefined && !str(n.size, 32)) ||
      (n.count !== undefined && ![1, 2, 4].includes(n.count))
    )
      throw new Error('画布节点数据无效。')
    ids.add(n.id)
  }
  for (const n of p.nodes)
    if (
      n.groupId &&
      (n.type === 'group' ||
        !p.nodes.some((g) => g.id === n.groupId && g.type === 'group'))
    )
      throw new Error('素材组引用无效。')
  const edgeIds = new Set<string>()
  for (const e of p.edges) {
    if (
      !e ||
      !id(e.id) ||
      edgeIds.has(e.id) ||
      !ids.has(e.from) ||
      !ids.has(e.to) ||
      e.from === e.to
    )
      throw new Error('画布连线数据无效。')
    edgeIds.add(e.id)
  }
  const runIds = new Set<string>()
  for (const r of p.runs) {
    if (
      !r ||
      !id(r.id) ||
      runIds.has(r.id) ||
      !id(r.nodeId) ||
      !id(r.sourceId) ||
      !str(r.prompt, 20000) ||
      !str(r.model, 128) ||
      !str(r.size, 32) ||
      !Array.isArray(r.referenceIds) ||
      r.referenceIds.length > 100 ||
      !r.referenceIds.every(hash) ||
      !Array.isArray(r.uploadedIds) ||
      r.uploadedIds.length > 100 ||
      !r.uploadedIds.every(id) ||
      (r.jobId !== undefined && !id(r.jobId)) ||
      (r.assetId !== undefined && !hash(r.assetId)) ||
      ![
        'preparing',
        'submitting',
        'queued',
        'processing',
        'succeeded',
        'failed',
        'unknown',
      ].includes(r.status)
    )
      throw new Error('画布任务数据无效。')
    runIds.add(r.id)
  }
  p.ownerId = ownerId
  if (assetIds(p).length > MAX_ASSETS)
    throw new Error('单张画布最多保存 1000 份素材，请拆分画布。')
  p.revision =
    Number.isSafeInteger(p.revision) && p.revision >= 0 ? p.revision : 0
  p.cloudVersion =
    Number.isSafeInteger(p.cloudVersion) && p.cloudVersion! > 0
      ? p.cloudVersion
      : null
  p.cloudEnabled = p.cloudEnabled === true
  return p
}
