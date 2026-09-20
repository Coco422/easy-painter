<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Plus,
  ImagePlus,
  Type,
  Sparkles,
  Hand,
  MousePointer2,
  Undo2,
  Redo2,
  Download,
  CloudUpload,
  Layers,
  Trash2,
  Maximize,
  Minus,
  Link2,
  X,
} from 'lucide-vue-next'
import CanvasNodeCard from './CanvasNodeCard.vue'
import {
  assetIds,
  clone,
  connect,
  generationInputs,
  MAX_NODES,
  newNode,
  removeNodes,
  uid,
  worldPoint,
  zoomAt,
} from '@/lib/canvas/model'
import type { CanvasNode, CanvasProject, Point } from '@/lib/canvas/model'
import { downloadBlob, exportProject } from '@/lib/canvas/storage'
import { useCanvasSession } from '@/lib/canvas/session'
const props = defineProps<{ initial: CanvasProject; canCloud: boolean }>()
const router = useRouter()
const session = useCanvasSession(props.initial)
const {
  project,
  selected,
  urls,
  meta,
  feedback,
  saveState,
  cloudState,
  busy,
  canUndo,
  canRedo,
} = session
const viewport = ref<HTMLElement>(),
  imageInput = ref<HTMLInputElement>(),
  panMode = ref(false),
  space = ref(false),
  connecting = ref<string | null>(null)
const size = ref({ width: 1000, height: 700 }),
  box = ref<{ start: Point; end: Point } | null>(null)
let observer: ResizeObserver | undefined,
  cancelGesture: (() => void) | undefined
const selectedSet = computed(() => new Set(selected.value))
const orderedNodes = computed(() =>
  [...project.value.nodes].sort(
    (a, b) => Number(b.type === 'group') - Number(a.type === 'group'),
  ),
)
const visibleNodes = computed(() => {
  const v = project.value.viewport
  return orderedNodes.value.filter(
    (n) =>
      selectedSet.value.has(n.id) ||
      ((n.x + n.width) * v.scale + v.x > -300 &&
        n.x * v.scale + v.x < size.value.width + 300 &&
        (n.y + n.height) * v.scale + v.y > -300 &&
        n.y * v.scale + v.y < size.value.height + 300),
  )
})
const nodeMap = computed(
  () => new Map(project.value.nodes.map((n) => [n.id, n])),
)
const uncertain = computed(() =>
  project.value.runs.filter(
    (r) =>
      ['unknown', 'preparing', 'submitting'].includes(r.status) || r.mediaError,
  ),
)
const boxStyle = computed(() =>
  box.value
    ? {
        left: `${Math.min(box.value.start.x, box.value.end.x)}px`,
        top: `${Math.min(box.value.start.y, box.value.end.y)}px`,
        width: `${Math.abs(box.value.end.x - box.value.start.x)}px`,
        height: `${Math.abs(box.value.end.y - box.value.start.y)}px`,
      }
    : {},
)
function point(event: { clientX: number; clientY: number }) {
  const rect = viewport.value!.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}
function center(): Point {
  return worldPoint(
    { x: size.value.width / 2 - 140, y: size.value.height / 2 - 130 },
    project.value.viewport,
  )
}
function add(type: CanvasNode['type'], position = center()) {
  if (project.value.nodes.length >= MAX_NODES) {
    feedback.value = '单张画布最多 300 个节点。'
    return
  }
  session.checkpoint()
  const node = newNode(type, position)
  if (type === 'generation') {
    const m = meta.value?.models.find((m) => m.enabled)
    node.model = m?.id ?? ''
    node.size = m?.supported_sizes[0] ?? 'auto'
  }
  project.value.nodes.push(node)
  selected.value = [node.id]
  session.changed()
  return node
}
function gesture(
  event: PointerEvent,
  move: (e: PointerEvent) => void,
  finish = () => {},
) {
  cancelGesture?.()
  const controller = new AbortController()
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture?.(event.pointerId)
  const stop = () => {
    controller.abort()
    cancelGesture = undefined
    finish()
  }
  cancelGesture = stop
  window.addEventListener(
    'pointermove',
    (e) => {
      if (e.pointerId === event.pointerId) move(e)
    },
    { signal: controller.signal },
  )
  window.addEventListener('pointerup', stop, { signal: controller.signal })
  window.addEventListener('pointercancel', stop, { signal: controller.signal })
}
function selectNode(node: CanvasNode, e: PointerEvent) {
  if (connecting.value) {
    try {
      session.checkpoint()
      connect(project.value, connecting.value, node.id)
      session.changed()
      connecting.value = null
    } catch (error) {
      feedback.value = (error as Error).message
    }
    return
  }
  if (e.shiftKey || e.metaKey || e.ctrlKey)
    selected.value = selectedSet.value.has(node.id)
      ? selected.value.filter((id) => id !== node.id)
      : [...selected.value, node.id]
  else if (!selectedSet.value.has(node.id)) selected.value = [node.id]
}
function dragNode(node: CanvasNode, e: PointerEvent) {
  if (e.button !== 0 && e.button !== 1) return
  if (panMode.value || space.value || e.button === 1) {
    pan(e)
    return
  }
  if (connecting.value) {
    selectNode(node, e)
    return
  }
  e.preventDefault()
  selectNode(node, e)
  const ids = new Set(selected.value)
  for (const n of project.value.nodes)
    if (n.groupId && ids.has(n.groupId)) ids.add(n.id)
  const originals = project.value.nodes
    .filter((n) => ids.has(n.id))
    .map((n) => ({ id: n.id, x: n.x, y: n.y }))
  let started = false
  gesture(
    e,
    (event) => {
      const dx = (event.clientX - e.clientX) / project.value.viewport.scale,
        dy = (event.clientY - e.clientY) / project.value.viewport.scale
      if (!started && Math.abs(dx) + Math.abs(dy) < 3) return
      if (!started) {
        session.checkpoint()
        started = true
      }
      for (const o of originals) {
        const n = nodeMap.value.get(o.id)
        if (n) {
          n.x = o.x + dx
          n.y = o.y + dy
        }
      }
    },
    () => {
      if (started) session.changed()
    },
  )
}
function resizeNode(node: CanvasNode, e: PointerEvent) {
  e.preventDefault()
  session.checkpoint()
  const w = node.width,
    h = node.height
  gesture(
    e,
    (event) => {
      node.width = Math.min(
        2400,
        Math.max(
          node.type === 'generation' ? 280 : 150,
          w + (event.clientX - e.clientX) / project.value.viewport.scale,
        ),
      )
      node.height = Math.min(
        2400,
        Math.max(
          node.type === 'generation' ? 330 : 100,
          h + (event.clientY - e.clientY) / project.value.viewport.scale,
        ),
      )
    },
    session.changed,
  )
}
function pan(e: PointerEvent) {
  e.preventDefault()
  const start = point(e),
    old = clone(project.value.viewport)
  gesture(
    e,
    (event) => {
      const now = point(event)
      project.value.viewport = {
        ...old,
        x: old.x + now.x - start.x,
        y: old.y + now.y - start.y,
      }
    },
    session.changed,
  )
}
function background(e: PointerEvent) {
  if (e.button !== 0 && e.button !== 1) return
  if (
    (e.target as Element).closest('[data-node-id],button,input,textarea,select')
  )
    return
  e.preventDefault()
  const start = point(e),
    old = clone(project.value.viewport),
    previous = e.shiftKey ? [...selected.value] : []
  if (panMode.value || space.value || e.button === 1) {
    pan(e)
  } else {
    selected.value = previous
    box.value = { start, end: start }
    connecting.value = null
    gesture(
      e,
      (event) => {
        const end = point(event)
        box.value = { start, end }
        const a = worldPoint(start, old),
          b = worldPoint(end, old)
        selected.value = [
          ...new Set([
            ...previous,
            ...project.value.nodes
              .filter(
                (n) =>
                  n.x + n.width >= Math.min(a.x, b.x) &&
                  n.x <= Math.max(a.x, b.x) &&
                  n.y + n.height >= Math.min(a.y, b.y) &&
                  n.y <= Math.max(a.y, b.y),
              )
              .map((n) => n.id),
          ]),
        ]
      },
      () => {
        box.value = null
      },
    )
  }
}
function zoom(
  factor: number,
  at = { x: size.value.width / 2, y: size.value.height / 2 },
) {
  project.value.viewport = zoomAt(
    project.value.viewport,
    at,
    project.value.viewport.scale * factor,
  )
  session.changed()
}
function wheel(e: WheelEvent) {
  if ((e.target as Element).closest('textarea,select,input')) return
  e.preventDefault()
  zoom(Math.exp(-e.deltaY * 0.0015), point(e))
}
function fit() {
  if (!project.value.nodes.length) {
    project.value.viewport = { x: 80, y: 70, scale: 1 }
    session.changed()
    return
  }
  const ns = project.value.nodes,
    minX = Math.min(...ns.map((n) => n.x)),
    minY = Math.min(...ns.map((n) => n.y)),
    maxX = Math.max(...ns.map((n) => n.x + n.width)),
    maxY = Math.max(...ns.map((n) => n.y + n.height))
  const scale = Math.max(
    0.1,
    Math.min(
      1.4,
      (size.value.width - 120) / (maxX - minX),
      (size.value.height - 120) / (maxY - minY),
    ),
  )
  project.value.viewport = {
    x: (size.value.width - (maxX - minX) * scale) / 2 - minX * scale,
    y: (size.value.height - (maxY - minY) * scale) / 2 - minY * scale,
    scale,
  }
  session.changed()
}
function derive(node: CanvasNode) {
  const target = add('generation', { x: node.x + node.width + 90, y: node.y })
  if (target) {
    connect(project.value, node.id, target.id)
    session.changed()
  }
}
function group() {
  const nodes = project.value.nodes.filter(
    (n) => selectedSet.value.has(n.id) && n.type !== 'group',
  )
  if (nodes.length < 2) return
  const minX = Math.min(...nodes.map((n) => n.x)),
    minY = Math.min(...nodes.map((n) => n.y)),
    maxX = Math.max(...nodes.map((n) => n.x + n.width)),
    maxY = Math.max(...nodes.map((n) => n.y + n.height))
  const n = add('group', { x: minX - 25, y: minY - 65 })
  if (!n) return
  n.width = maxX - minX + 50
  n.height = maxY - minY + 90
  for (const child of nodes) child.groupId = n.id
  session.changed()
}
function remove() {
  if (!selected.value.length) return
  session.checkpoint()
  removeNodes(project.value, selected.value)
  selected.value = []
  session.changed()
}
function removeEdge(id: string) {
  session.checkpoint()
  project.value.edges = project.value.edges.filter((e) => e.id !== id)
  session.changed()
}
function edgePath(from: string, to: string) {
  const a = nodeMap.value.get(from),
    b = nodeMap.value.get(to)
  if (!a || !b) return ''
  const x = a.x + a.width,
    y = a.y + a.height / 2,
    xx = b.x,
    yy = b.y + b.height / 2,
    d = Math.max(60, Math.abs(xx - x) / 2)
  return `M ${x} ${y} C ${x + d} ${y}, ${xx - d} ${yy}, ${xx} ${yy}`
}
async function importImages(files: FileList | File[], position = center()) {
  for (const [i, file] of Array.from(files).entries()) {
    try {
      await session.addImage(file, file.name, {
        x: position.x + i * 30,
        y: position.y + i * 30,
      })
    } catch (e) {
      feedback.value = (e as Error).message
      break
    }
  }
}
function drop(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer?.files.length)
    void importImages(
      e.dataTransfer.files,
      worldPoint(point(e), project.value.viewport),
    )
}
async function exportFile() {
  try {
    downloadBlob(
      await exportProject(project.value, session.pendingAssets),
      `${project.value.title}.epcanvas.json`,
    )
  } catch (e) {
    feedback.value = (e as Error).message
  }
}
function keydown(e: KeyboardEvent) {
  if ((e.target as Element).closest('input,textarea,select,[contenteditable]'))
    return
  if (e.code === 'Space') {
    space.value = true
    e.preventDefault()
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
    e.preventDefault()
    session.historyMove(e.shiftKey ? 'redo' : 'undo')
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault()
    remove()
  }
  if (e.key === 'Escape') {
    connecting.value = null
    selected.value = []
  }
}
function keyup(e: KeyboardEvent) {
  if (e.code === 'Space') space.value = false
}
function blur() {
  space.value = false
  cancelGesture?.()
}
function paste(e: ClipboardEvent) {
  if ((e.target as Element).closest('input,textarea,[contenteditable]')) return
  const files = Array.from(e.clipboardData?.files ?? []).filter((f) =>
    f.type.startsWith('image/'),
  )
  if (files.length) {
    e.preventDefault()
    void importImages(files)
  }
}
async function leave() {
  try {
    await session.flush()
    return true
  } catch (e) {
    feedback.value = (e as Error).message
    return window.confirm(
      '本地保存失败，离开会丢失尚未保存的修改。建议取消并导出项目备份。仍要离开吗？',
    )
  }
}
onBeforeRouteLeave(leave)
onBeforeRouteUpdate(leave)
onMounted(() => {
  observer = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect
    if (rect) size.value = { width: rect.width, height: rect.height }
  })
  if (viewport.value) observer.observe(viewport.value)
  window.addEventListener('keydown', keydown)
  window.addEventListener('keyup', keyup)
  window.addEventListener('blur', blur)
  window.addEventListener('paste', paste)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancelGesture?.()
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('keyup', keyup)
  window.removeEventListener('blur', blur)
  window.removeEventListener('paste', paste)
})
</script>
<template>
  <section class="canvas-editor">
    <div class="canvas-topbar">
      <button
        class="icon-button"
        title="返回画布列表"
        @click="router.push('/canvas')"
      >
        <ArrowLeft :size="18" />
      </button>
      <div class="canvas-name">
        <input
          v-model="project.title"
          aria-label="画布名称"
          maxlength="120"
          @input="session.changed()"
        /><span :class="{ warning: saveState === '保存失败' }">{{
          saveState
        }}</span>
      </div>
      <div class="topbar-spacer" />
      <span v-if="cloudState" class="cloud-state">{{ cloudState }}</span>
      <button
        v-if="saveState === '保存失败'"
        class="toolbar-button"
        @click="session.flush().catch((e) => (feedback = e.message))"
      >
        重试本地保存
      </button>
      <button v-if="canCloud" class="toolbar-button" @click="session.sync">
        <CloudUpload :size="16" />{{
          project.cloudEnabled ? '立即同步' : '开启云端同步'
        }}
      </button>
      <button
        v-if="project.cloudEnabled"
        class="toolbar-button"
        @click="session.stopSync"
      >
        关闭自动同步
      </button>
      <button class="toolbar-button" @click="exportFile">
        <Download :size="16" />导出项目
      </button>
    </div>
    <div v-if="feedback" class="canvas-feedback" role="status">
      {{ feedback
      }}<button aria-label="关闭提示" @click="feedback = ''">
        <X :size="14" />
      </button>
    </div>
    <div v-if="uncertain.length" class="canvas-recovery">
      <span>{{ uncertain.length }} 个任务需要处理</span
      ><button
        v-for="run in uncertain"
        :key="run.id"
        @click="session.retry(run)"
      >
        {{ run.mediaError ? '重新保存图片' : '确认任务' }} ·
        {{ run.prompt.slice(0, 12) }}
      </button>
    </div>
    <div
      ref="viewport"
      class="canvas-viewport"
      :class="{ panning: panMode || space }"
      :style="{
        backgroundSize: `${24 * project.viewport.scale}px ${24 * project.viewport.scale}px`,
        backgroundPosition: `${project.viewport.x}px ${project.viewport.y}px`,
      }"
      @pointerdown="background"
      @wheel="wheel"
      @dragover.prevent
      @drop="drop"
      @dblclick="
        (e) => {
          if (e.target === viewport)
            add('text', worldPoint(point(e), project.viewport))
        }
      "
    >
      <div
        class="canvas-world"
        :style="{
          transform: `translate(${project.viewport.x}px,${project.viewport.y}px) scale(${project.viewport.scale})`,
        }"
      >
        <svg class="canvas-edges">
          <g v-for="edge in project.edges" :key="edge.id">
            <path
              :d="edgePath(edge.from, edge.to)"
              class="edge-hit"
              @pointerdown.stop
              @dblclick.stop="removeEdge(edge.id)"
            >
              <title>双击移除连线</title>
            </path>
            <path :d="edgePath(edge.from, edge.to)" class="edge-line" />
          </g>
        </svg>
        <CanvasNodeCard
          v-for="node in visibleNodes"
          :key="node.id"
          :node="node"
          :selected="selectedSet.has(node.id)"
          :image="
            urls[
              node.assetId ??
                project.runs.find((r) => r.nodeId === node.id)?.assetId ??
                ''
            ]
          "
          :run="project.runs.find((r) => r.nodeId === node.id)"
          :models="meta?.models ?? []"
          :busy="busy"
          :input-count="generationInputs(project, node.id).assets.length"
          @select="selectNode(node, $event)"
          @drag="dragNode(node, $event)"
          @resize="resizeNode(node, $event)"
          @checkpoint="session.checkpoint"
          @edit="session.changed"
          @generate="session.generate(node.id)"
          @retry="
            session.retry(project.runs.find((r) => r.nodeId === node.id)!)
          "
          @derive="derive(node)"
          @connect="connecting = node.id"
        />
      </div>
      <div v-if="box" class="selection-box" :style="boxStyle" />
      <div v-if="!project.nodes.length" class="canvas-empty">
        <span class="empty-kicker">让灵感有地方展开</span>
        <h2>从一张图，或一个想法开始</h2>
        <p>拖入参考图、记录提示词，把每次尝试留在画布上。</p>
        <div>
          <button class="toolbar-button primary" @click="add('generation')">
            <Sparkles :size="16" />开始生成</button
          ><button class="toolbar-button" @click="imageInput?.click()">
            <ImagePlus :size="16" />添加图片
          </button>
        </div>
      </div>
      <div class="canvas-tools" @pointerdown.stop>
        <button
          :class="{ active: !panMode }"
          title="选择工具"
          aria-label="选择工具"
          @click="panMode = false"
        >
          <MousePointer2 :size="19" /></button
        ><button
          :class="{ active: panMode }"
          title="移动画布（按住空格）"
          aria-label="移动画布"
          @click="panMode = true"
        >
          <Hand :size="19" /></button
        ><i />
        <button
          title="添加图片"
          aria-label="添加图片"
          @click="imageInput?.click()"
        >
          <ImagePlus :size="19" /></button
        ><button title="添加文本" aria-label="添加文本" @click="add('text')">
          <Type :size="19" /></button
        ><button
          title="添加生成节点"
          aria-label="添加生成节点"
          @click="add('generation')"
        >
          <Sparkles :size="19" /></button
        ><i />
        <button
          :disabled="!canUndo"
          title="撤销"
          aria-label="撤销"
          @click="session.historyMove('undo')"
        >
          <Undo2 :size="18" /></button
        ><button
          :disabled="!canRedo"
          title="重做"
          aria-label="重做"
          @click="session.historyMove('redo')"
        >
          <Redo2 :size="18" />
        </button>
      </div>
      <div v-if="selected.length" class="selection-tools" @pointerdown.stop>
        <span>已选 {{ selected.length }} 项</span
        ><button v-if="selected.length >= 2" @click="group">
          <Layers :size="14" />打组</button
        ><button
          v-if="
            selected.length === 1 && nodeMap.get(selected[0])?.type === 'group'
          "
          @click="remove"
        >
          解散组</button
        ><button @click="remove"><Trash2 :size="14" />移除</button>
      </div>
      <div v-if="connecting" class="connect-hint">
        <Link2 :size="15" />点击一个生成节点以建立连接<button
          @click="connecting = null"
        >
          取消
        </button>
      </div>
      <div class="canvas-bottom">
        <span
          >{{ project.nodes.length }} 个节点 ·
          {{ assetIds(project).length }} 份素材<span class="desktop-hint">
            · 空格拖动 / 滚轮缩放 / 双击连线移除</span
          ></span
        >
        <div class="zoom-controls">
          <button aria-label="缩小" @click="zoom(0.8)">
            <Minus :size="15" /></button
          ><span>{{ Math.round(project.viewport.scale * 100) }}%</span
          ><button aria-label="放大" @click="zoom(1.25)">
            <Plus :size="15" /></button
          ><button aria-label="显示全部" title="显示全部" @click="fit">
            <Maximize :size="15" />
          </button>
        </div>
      </div>
    </div>
    <input
      ref="imageInput"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      multiple
      hidden
      @change="
        (e) => {
          const input = e.target as HTMLInputElement
          if (input.files) void importImages(input.files)
          input.value = ''
        }
      "
    />
  </section>
</template>
<style scoped>
.canvas-editor {
  height: calc(100dvh - 160px);
  min-height: 560px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 16px;
  overflow: hidden;
  background: var(--bg-surface);
}
.canvas-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.canvas-name {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.canvas-name input {
  font: inherit;
  font-size: 15px;
  font-weight: 600;
  max-width: 230px;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  outline: none;
}
.canvas-name span,
.cloud-state {
  font-size: 11px;
  color: var(--text-muted);
}
.canvas-name .warning {
  color: var(--error);
}
.topbar-spacer {
  flex: 1;
}
button {
  font: inherit;
  cursor: pointer;
  color: var(--text-primary);
}
.icon-button {
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  padding: 7px;
}
.toolbar-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-surface);
  font-size: 12px;
}
.toolbar-button.primary {
  background: var(--accent);
  color: var(--text-inverse);
  border-color: var(--accent);
}
.canvas-viewport {
  position: relative;
  flex: 1;
  overflow: hidden;
  background-color: var(--bg-deep);
  background-image: radial-gradient(
    var(--text-muted) 0.65px,
    transparent 0.65px
  );
  touch-action: none;
  user-select: none;
}
.canvas-viewport.panning {
  cursor: grab;
}
.canvas-world {
  position: absolute;
  inset: 0;
  transform-origin: 0 0;
  pointer-events: none;
}
.canvas-edges {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: visible;
}
.edge-line {
  stroke: var(--accent);
  stroke-width: 2;
  fill: none;
  opacity: 0.55;
  pointer-events: none;
}
.edge-hit {
  stroke: transparent;
  stroke-width: 18;
  fill: none;
  pointer-events: stroke;
  cursor: pointer;
}
.selection-box {
  position: absolute;
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  pointer-events: none;
}
.canvas-empty {
  position: absolute;
  left: 50%;
  top: 43%;
  transform: translate(-50%, -50%);
  width: min(530px, 80%);
  text-align: center;
  pointer-events: none;
}
.empty-kicker {
  font-size: 12px;
  color: var(--accent);
  letter-spacing: 3px;
}
.canvas-empty h2 {
  font-size: 27px;
  font-weight: 500;
  margin: 16px 0 12px;
}
.canvas-empty p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
}
.canvas-empty > div {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 24px;
  pointer-events: auto;
}
.canvas-tools {
  position: absolute;
  left: 18px;
  top: 20px;
  display: flex;
  flex-direction: column;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-md);
  gap: 3px;
}
.canvas-tools button {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  background: transparent;
  border: 0;
  border-radius: 7px;
}
.canvas-tools button:hover,
.canvas-tools button.active {
  background: var(--accent-soft);
  color: var(--accent);
}
button:disabled {
  opacity: 0.3;
  cursor: default;
}
.canvas-tools i {
  height: 1px;
  background: var(--border);
  margin: 4px;
}
.selection-tools,
.connect-hint {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--bg-surface);
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: var(--shadow-sm);
  font-size: 12px;
  white-space: nowrap;
}
.selection-tools button,
.connect-hint button {
  display: flex;
  align-items: center;
  gap: 5px;
  border: 0;
  background: transparent;
  padding: 4px;
}
.connect-hint {
  top: 68px;
  color: var(--accent);
}
.canvas-bottom {
  position: absolute;
  bottom: 12px;
  left: 18px;
  right: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  pointer-events: none;
  font-size: 11px;
  color: var(--text-muted);
}
.zoom-controls {
  display: flex;
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  pointer-events: auto;
  padding: 4px;
}
.zoom-controls button {
  border: 0;
  background: transparent;
  padding: 7px;
  display: grid;
  place-items: center;
}
.zoom-controls span {
  min-width: 43px;
  text-align: center;
}
.canvas-feedback {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: var(--error-soft);
  font-size: 12px;
  color: var(--error);
  line-height: 1.6;
}
.canvas-feedback button {
  background: transparent;
  border: 0;
  display: flex;
}
.canvas-recovery {
  padding: 8px 16px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  background: var(--accent-soft);
  font-size: 12px;
  align-items: center;
}
.canvas-recovery button {
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--bg-surface);
  font-size: 11px;
  padding: 5px;
}
@media (max-width: 700px) {
  .canvas-editor {
    height: calc(100dvh - 190px);
    min-height: 550px;
    border-radius: 10px;
  }
  .canvas-topbar {
    gap: 8px;
    padding: 10px;
  }
  .canvas-name input {
    max-width: 160px;
  }
  .toolbar-button {
    padding: 8px;
  }
  .cloud-state,
  .desktop-hint {
    display: none;
  }
  .canvas-empty h2 {
    font-size: 21px;
  }
  .canvas-tools {
    left: 8px;
    top: 10px;
  }
  .canvas-bottom {
    left: 8px;
    right: 8px;
  }
  .canvas-bottom > span {
    max-width: 130px;
  }
  .canvas-empty {
    width: 75%;
    left: 56%;
  }
}
</style>
