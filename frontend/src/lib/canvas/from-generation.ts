import { clone, newNode, MAX_NODES, uid } from './model.ts'
import type { CanvasProject } from './model.ts'

export function appendGenerationImage(project: CanvasProject, source: {
  jobId: string; assetId: string; label: string; prompt: string; model: string; size: string; width: number; height: number
}): CanvasProject {
  if (project.nodes.length + 3 > MAX_NODES) throw new Error('画布节点已达上限，请新建画布。')
  if (!(source.width > 0 && source.height > 0)) throw new Error('无法读取图片尺寸。')
  const next = clone(project)
  const x = next.nodes.length ? Math.max(...next.nodes.map(node => node.x + node.width)) + 80 : 0
  const image = newNode('image', { x, y: 0 })
  image.title = source.label
  image.assetId = source.assetId
  image.width = 520
  image.height = Math.max(100, Math.min(700, 520 * source.height / source.width + 40))
  const generation = newNode('generation', { x: x + 600, y: 0 })
  generation.title = '继续创作'
  generation.model = source.model
  generation.size = source.size
  const note = newNode('text', { x, y: image.height + 40 })
  note.title = '原始提示词与来源'
  note.width = 520
  note.text = `${source.prompt}\n\n模型：${source.model} · 尺寸：${source.size}\n来源任务：${source.jobId}`
  next.nodes.push(image, generation, note)
  next.edges.push({ id: uid(), from: image.id, to: generation.id })
  next.viewport = { x: 90 - x * .7, y: 50, scale: .7 }
  next.updatedAt = new Date().toISOString()
  // An imported result is an image asset. It must never submit or replay a paid run.
  return next
}
