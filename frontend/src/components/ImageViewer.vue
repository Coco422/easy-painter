<script setup lang="ts">
import { cloneVNode, h, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NImagePreview } from 'naive-ui'
import type { ImageRenderToolbarProps } from 'naive-ui'

const props = defineProps<{ src: string; show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean]; download: [] }>()
const session = ref(0)
const toolbar = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
let zoomIn: (() => void) | undefined
let zoomOut: (() => void) | undefined
let lastWheel = 0

// Keep the library's transforms, gestures and toolbar actions. Native buttons
// add names and keyboard activation to the stock icon nodes.
function renderToolbar({ nodes }: ImageRenderToolbarProps) {
  zoomIn = nodes.zoomIn.props?.onClick
  zoomOut = nodes.zoomOut.props?.onClick
  const actions = [
    ['rotateCounterclockwise', '向左旋转'], ['rotateClockwise', '向右旋转'],
    ['resizeToOriginalSize', '原始尺寸'], ['zoomOut', '缩小'],
    ['zoomIn', '放大'], ['download', '下载原图'], ['close', '关闭图片预览'],
  ] as const
  return h('div', { ref: toolbar, role: 'toolbar', 'aria-label': '图片浏览工具栏', style: { display: 'flex', alignItems: 'center' } }, actions.map(([key, label]) => {
    const node = nodes[key]
    const icon = cloneVNode(node)
    if (icon.props) icon.props = { ...icon.props, onClick: undefined }
    return h('button', {
      type: 'button', title: label, 'aria-label': label,
      style: { border: 0, background: 'transparent', color: 'inherit', cursor: 'pointer', padding: '8px' },
      onClick: key === 'download' ? () => emit('download') : node.props?.onClick,
    }, [icon])
  }))
}

// The installed library exposes toolbar/keyboard zoom, but consumes wheel
// events without zooming. Delegate the wheel to those same library actions.
function wheel(event: WheelEvent) {
  if (!props.show || !toolbar.value?.closest('.n-image-preview-container')?.contains(event.target as Node)) return
  event.preventDefault()
  if (!event.deltaY || Date.now() - lastWheel < 100) return
  lastWheel = Date.now()
  if (event.deltaY < 0) zoomIn?.()
  else zoomOut?.()
}

// Escape belongs to the top image viewer, not to an underlying details modal
// or admin drawer. Scaling and all other shortcuts remain library-owned.
function handleViewerKeydown(event: KeyboardEvent) {
  if (props.show && event.key === 'Escape') {
    event.preventDefault()
    event.stopImmediatePropagation()
    emit('update:show', false)
  } else if (props.show && event.key === 'Tab') {
    const buttons = toolbar.value?.querySelectorAll<HTMLButtonElement>('button')
    if (!buttons?.length) return
    const first = buttons[0], last = buttons[buttons.length - 1]
    if (!toolbar.value?.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
      event.preventDefault()
      ;(event.shiftKey ? last : first)?.focus()
    }
    event.stopImmediatePropagation()
  }
}
watch(() => props.show, show => {
  if (show) {
    previousFocus = document.activeElement as HTMLElement | null
    window.addEventListener('keydown', handleViewerKeydown, true)
    window.addEventListener('wheel', wheel, { capture: true, passive: false })
    void nextTick(() => { if (props.show) toolbar.value?.querySelector('button')?.focus() })
  }
  else {
    window.removeEventListener('keydown', handleViewerKeydown, true)
    window.removeEventListener('wheel', wheel, true)
    session.value++ // Reopening starts with fresh library transform state.
    previousFocus?.focus()
  }
}, { immediate: true })
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleViewerKeydown, true)
  window.removeEventListener('wheel', wheel, true)
})
</script>

<template>
  <NImagePreview :key="session" :src="src" :show="show" :render-toolbar="renderToolbar" @update:show="emit('update:show', $event)" />
</template>
