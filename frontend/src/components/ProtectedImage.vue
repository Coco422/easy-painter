<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { authState, getAdminAuthHeader, getAuthHeader } from '@/lib/auth'
import { mediaAvailable, retryableMediaStatus, sameOriginMedia } from '@/lib/media-state'
import { useMediaClock } from '@/composables/useMediaClock'

const props = withDefaults(defineProps<{
  src?: string | null; state?: string; expiresAt?: string | null; alt?: string; eager?: boolean; admin?: boolean
}>(), { state: 'available', alt: '', eager: false, admin: false })
const emit = defineEmits<{ invalid: []; loaded: [event: Event] }>()
const now = useMediaClock()
const frame = ref<HTMLElement | null>(null)
const visible = ref(false)
const objectUrl = ref('')
const failed = ref(false)
const retrying = ref(false)
const allowed = computed(() => mediaAvailable(props.state, props.expiresAt, now.value))
let observer: IntersectionObserver | undefined
let controller: AbortController | undefined
let retryTimer: ReturnType<typeof setTimeout> | undefined
let generation = 0

function clear() {
  generation += 1
  controller?.abort()
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = undefined
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  objectUrl.value = ''
  retrying.value = false
}
function begin() {
  clear()
  failed.value = false
  if (!props.src || !allowed.value || (!visible.value && !props.eager)) return
  const version = generation
  controller = new AbortController()
  const signal = controller.signal
  const src = props.src
  const local = sameOriginMedia(src, window.location.origin)
  const attempt = async (retried = false) => {
    if (signal.aborted || version !== generation || !allowed.value) return
    try {
      const response = await fetch(src, {
        headers: local ? (props.admin ? getAdminAuthHeader() : getAuthHeader()) : {},
        credentials: local ? 'same-origin' : 'omit', signal, cache: 'default',
      })
      if (!response.ok) {
        if (retryableMediaStatus(response.status)) throw new Error('temporary')
        failed.value = true
        if ([401, 403, 404, 410].includes(response.status)) emit('invalid')
        return
      }
      const blob = await response.blob()
      if (signal.aborted || version !== generation || !allowed.value) return
      objectUrl.value = URL.createObjectURL(blob)
      retrying.value = false
    } catch {
      if (signal.aborted || version !== generation || !allowed.value) return
      if (!retried) {
        retrying.value = true
        retryTimer = setTimeout(() => { void attempt(true) }, 2000)
      } else { failed.value = true; retrying.value = false }
    }
  }
  void attempt()
}
watch([() => props.src, allowed, visible, () => props.admin ? authState.adminToken : authState.token], begin)
onMounted(() => {
  if (props.eager || !('IntersectionObserver' in window)) visible.value = true
  else {
    observer = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) { visible.value = true; observer?.disconnect() }
    }, { rootMargin: '160px' })
    if (frame.value) observer.observe(frame.value)
  }
})
onBeforeUnmount(() => { observer?.disconnect(); clear() })
</script>
<template>
  <span ref="frame" class="protected-image">
    <img v-if="allowed && objectUrl && !failed" :src="objectUrl" :alt="alt" @load="emit('loaded', $event)" @error="failed = true" />
    <span v-else class="image-placeholder" role="status">
      <span v-if="!allowed">{{ state === 'none' ? '暂无生成图片' : '图片已失效' }}</span>
      <span v-else-if="!src">预览准备中，可打开详情</span>
      <span v-else-if="failed">图片暂时无法显示</span>
      <span v-else>{{ retrying ? '连接不稳定，重试一次…' : '正在加载图片…' }}</span>
    </span>
  </span>
</template>
<style scoped>
.protected-image { display: block; width: 100%; height: 100%; min-height: 120px; background: var(--bg-elevated); overflow: hidden; }
img { display: block; width: 100%; height: 100%; object-fit: contain; }
.image-placeholder { display: grid; place-items: center; height: 100%; min-height: 140px; padding: 24px; color: var(--text-muted); font-size: 13px; text-align: center; }
</style>
