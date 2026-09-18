<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { getAuthHeader } from '@/lib/auth'
import { useMediaClock } from '@/composables/useMediaClock'
import { mediaAvailable } from '@/lib/media-state'
import { imageDownloadFilename } from '@/lib/image-download'
import { resolveImageLayout } from '@/lib/image-layout'
import type { JobDetailResponse } from '@/lib/types'

const props = defineProps<{
  job: JobDetailResponse | null
  isPolling: boolean
}>()

const emit = defineEmits<{
  retry: [job: JobDetailResponse]
  dismiss: [jobId: string]
  addToGallery: [job: JobDetailResponse]
  refreshMedia: [job: JobDetailResponse]
  details: [job: JobDetailResponse]
}>()

const TYPE_INTERVAL_MS = 54
const MESSAGE_HOLD_MS = 2200
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

const MAIN_LOADING_LINES = [
  '给云层办理临时身份证',
  '把太阳光调成七成熟',
  '正在检查像素有没有带伞',
  '给参考图倒一杯热水',
  '把远处的山重新摆正',
  '让草地先深呼吸三秒',
  '给阴影安排临时工位',
  '把构图里的风扇调到低速',
  '正在劝说色块别抢镜',
  '给高光贴上易碎标签',
  '把画面边角擦到发亮',
  '正在训练线条排队入场',
  '给背景申请一点存在感',
  '把灵感切成方便入口的小块',
  '正在给细节分发工作证',
  '让镜头先假装路过一下',
]

const LOADING_LOG_LINES = [
  '检查画布四角是否端正',
  '给主角留出呼吸空间',
  '把过亮的云轻轻按回去',
  '同步颜料库存和想象力',
  '给参考图安排贵宾席',
  '校准远处那块不太听话的蓝色',
  '正在把噪点请到休息区',
  '为细节准备第二杯咖啡',
  '重新确认这条光线没有迟到',
  '把空气感调到刚好能闻见',
  '检查像素队列是否有插队',
  '正在给边缘做柔和体操',
  '把背景音量调低一点',
  '为最终成图预热相框',
  '提醒阴影不要擅自加班',
  '正在给画面取一个临时小名',
]

const LOADING_STAGES = ['播种轮廓', '驯服光线', '烘焙细节', '封装成图']

const now = useMediaClock()
const typedText = ref('')
const activeMessageIndex = ref(0)
const prefersReducedMotion = ref(false)
const actualImageAspectRatio = ref<string | null>(null)
const resultImageLoaded = ref(false)
const mediaRefreshRequested = ref(false)
const downloadError = ref('')
let downloadController: AbortController | undefined
const downloading = ref(false)
let typingTimer: number | undefined
let messageTimer: number | undefined
let reducedMotionQuery: MediaQueryList | null = null

const available = computed(() => !!props.job && mediaAvailable(props.job.media_state ?? 'none', props.job.media_expires_at, now.value))
watch(available, value => { if (!value) downloadController?.abort() })
const liveJob = computed(() => (props.job && isLiveStatus(props.job.status) ? props.job : null))
const loadingSeed = computed(() => {
  if (!liveJob.value) return 0
  return hashSeed(`${liveJob.value.job_id}:${liveJob.value.created_at}:${liveJob.value.status}`)
})
const messageIndexes = computed(() => pickIndexes(MAIN_LOADING_LINES.length, loadingSeed.value, 7))
const activeMessage = computed(() => {
  const indexes = messageIndexes.value
  const messageIndex = indexes[activeMessageIndex.value % indexes.length] ?? 0
  return MAIN_LOADING_LINES[messageIndex] ?? MAIN_LOADING_LINES[0]
})
const visibleLogLines = computed(() => {
  const logTick = Math.floor(now.value / 5200)
  return pickIndexes(LOADING_LOG_LINES.length, loadingSeed.value + logTick * 131, 3).map((index) => LOADING_LOG_LINES[index])
})
const loadingProgress = computed(() => {
  if (!liveJob.value) return 0
  const createdAt = Date.parse(liveJob.value.created_at)
  const elapsedMs = Number.isFinite(createdAt) ? Math.max(0, now.value - createdAt) : 0
  const statusBoost = liveJob.value.status === 'processing' ? 14 : 0
  return Math.min(96, Math.max(8, 8 + statusBoost + Math.floor(elapsedMs / 2500)))
})
const loadingStage = computed(() => {
  const stageIndex = Math.min(LOADING_STAGES.length - 1, Math.floor(loadingProgress.value / 25))
  return LOADING_STAGES[stageIndex] ?? LOADING_STAGES[0]
})
const loadingModeText = computed(() => (liveJob.value?.status === 'queued' ? '等待队列响应' : '正在同步画面'))
const displayedLoadingText = computed(() => {
  if (prefersReducedMotion.value) return activeMessage.value
  return typedText.value || activeMessage.value.slice(0, 1)
})
const imageLayout = computed(() => resolveImageLayout(props.job?.size, props.job?.aspect_ratio))
const displayedImageAspectRatio = computed(() => actualImageAspectRatio.value ?? imageLayout.value.aspectRatio)
const billingLabel = computed(() => ({
  not_charged: '未扣费',
  reserved: '已预扣',
  settled: '已结算',
  refunded: '已全额退款',
}[props.job?.billing_status ?? 'not_charged'] ?? props.job?.billing_status))

function statusText(status: JobDetailResponse['status']) {
  switch (status) {
    case 'queued':
      return '排队中'
    case 'processing':
      return '生成中'
    case 'succeeded':
      return '生成成功'
    case 'failed':
      return '生成失败'
    default:
      return status
  }
}

function isLiveStatus(status: JobDetailResponse['status']) {
  return status === 'queued' || status === 'processing'
}

function placeholderText(job: JobDetailResponse) {
  if (job.status === 'failed') return '生成失败'
  if (job.status === 'queued') return '等待执行'
  return '异步创作中'
}

function markResultImageLoaded(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.naturalWidth > 0 && image.naturalHeight > 0) {
    actualImageAspectRatio.value = `${image.naturalWidth} / ${image.naturalHeight}`
  }
  resultImageLoaded.value = true
  mediaRefreshRequested.value = false
}

function requestMediaRefresh() {
  if (!props.job || mediaRefreshRequested.value) return
  mediaRefreshRequested.value = true
  emit('refreshMedia', props.job)
}

function openImagePreview() {
  if (!resultImageLoaded.value) return
  if (props.job && available.value) emit('details', props.job)
}

async function downloadImage() {
  const job = props.job
  if (!job || job.status !== 'succeeded' || !job.image_url || !available.value || downloading.value) return
  downloading.value = true
  downloadError.value = ''
  downloadController = new AbortController()
  try {
    const response = await fetch(job.image_url, { headers: getAuthHeader(), signal: downloadController.signal })
    if (!response.ok) throw new Error('download failed')
    const blob = await response.blob()
    if (!available.value) return
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = imageDownloadFilename(job.job_id, blob.type)
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  } catch {
    if (!downloadController.signal.aborted) downloadError.value = '图片暂时无法下载。'
  } finally {
    downloading.value = false
  }
}

function hashSeed(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function pickIndexes(length: number, seed: number, count: number) {
  if (length <= 0) return []
  const selected: number[] = []
  let cursor = seed >>> 0
  while (selected.length < Math.min(count, length)) {
    cursor = Math.imul(cursor + 0x9e3779b9, 2654435761) >>> 0
    let candidate = cursor % length
    while (selected.includes(candidate)) {
      candidate = (candidate + 1) % length
    }
    selected.push(candidate)
  }
  return selected
}

function clearTypingTimers() {
  if (typingTimer !== undefined) {
    window.clearTimeout(typingTimer)
    typingTimer = undefined
  }
  if (messageTimer !== undefined) {
    window.clearTimeout(messageTimer)
    messageTimer = undefined
  }
}

function runTypewriter() {
  clearTypingTimers()
  const message = activeMessage.value
  if (!liveJob.value || prefersReducedMotion.value) {
    typedText.value = message
    return
  }

  let charIndex = 0
  typedText.value = ''
  const typeNext = () => {
    charIndex += 1
    typedText.value = message.slice(0, charIndex)
    if (charIndex >= message.length) {
      messageTimer = window.setTimeout(() => {
        activeMessageIndex.value = (activeMessageIndex.value + 1) % messageIndexes.value.length
        runTypewriter()
      }, MESSAGE_HOLD_MS)
      return
    }
    typingTimer = window.setTimeout(typeNext, TYPE_INTERVAL_MS)
  }
  typeNext()
}

function resetLoadingSequence() {
  const indexes = messageIndexes.value
  activeMessageIndex.value = indexes.length > 0 ? loadingSeed.value % indexes.length : 0
  runTypewriter()
}

function updateReducedMotion(event: MediaQueryList | MediaQueryListEvent) {
  prefersReducedMotion.value = event.matches
  runTypewriter()
}

function logIndexLabel(index: number) {
  return String(index + 1).padStart(2, '0')
}

watch(
  () => (liveJob.value ? `${liveJob.value.job_id}:${liveJob.value.created_at}:${liveJob.value.status}` : ''),
  () => resetLoadingSequence(),
)

watch(
  () => `${props.job?.job_id ?? ''}:${props.job?.image_url ?? ''}`,
  () => {
    actualImageAspectRatio.value = null
    resultImageLoaded.value = false
  },
)

onMounted(() => {
  reducedMotionQuery = window.matchMedia(REDUCED_MOTION_QUERY)
  prefersReducedMotion.value = reducedMotionQuery.matches
  reducedMotionQuery.addEventListener('change', updateReducedMotion)
  resetLoadingSequence()
})

onBeforeUnmount(() => {
  downloadController?.abort()
  clearTypingTimers()
  reducedMotionQuery?.removeEventListener('change', updateReducedMotion)
})
</script>

<template>
  <section v-if="job" class="current-job" :class="`current-job--${job.status}`">
    <div class="current-job-copy">
      <p class="section-label">当前任务</p>
      <div class="status-line">
        <strong>{{ statusText(job.status) }}</strong>
        <span v-if="isPolling" class="status-dot" />
      </div>
      <p class="job-prompt">{{ job.prompt }}</p>
      <div class="job-billing-meta">
        <span>{{ job.model_label || job.model }}</span>
        <span v-if="job.provider_name">{{ job.provider_name }}</span>
        <span>{{ job.credit_cost }} 丝 / 张</span>
        <strong :class="`billing-${job.billing_status}`">{{ billingLabel }}</strong>
      </div>
      <MediaExpiry v-if="job.status === 'succeeded'" :state="job.media_state ?? 'none'" :expires-at="job.media_expires_at" :permanent="job.retention_kind === 'permanent'" />
      <p v-if="downloadError" class="job-error">{{ downloadError }}</p>
      <p v-if="isLiveStatus(job.status) && job.error_message" class="job-hint">{{ job.error_message }}</p>
      <p v-if="job.status === 'failed'" class="job-error">{{ job.error_message || '任务已失败，请重试或结束。' }}</p>
      <p v-if="job.status === 'failed' && job.billing_status === 'refunded'" class="job-refund-note">
        本任务未交付图片，{{ job.credit_cost }} 丝已全额退回余额。
      </p>
      <div v-if="job.status === 'failed'" class="current-job-actions">
        <button type="button" class="secondary-button" @click="emit('retry', job)">重新生成</button>
        <button type="button" class="ghost-button" @click="emit('dismiss', job.job_id)">结束</button>
      </div>
      <div v-if="job.status === 'succeeded' && available" class="current-job-actions">
        <button type="button" class="secondary-button" @click="emit('addToGallery', job)">加入画廊</button>
        <button type="button" class="ghost-button" :disabled="downloading" :aria-busy="downloading" @click="downloadImage">
          {{ downloading ? '下载中…' : '下载图片' }}
        </button>
        <button type="button" class="ghost-button" @click="emit('dismiss', job.job_id)">关闭</button>
      </div>
    </div>

    <div
      class="current-job-visual"
      :class="{ 'is-landscape': imageLayout.ratio >= 1.45 }"
      :style="{ aspectRatio: displayedImageAspectRatio }"
    >
      <ProtectedImage
        v-if="job.status === 'succeeded'"
        :src="job.image_url"
        :state="job.media_state"
        :expires-at="job.media_expires_at"
        class="current-job-result-image"
        alt="当前任务结果图"
        eager
        @loaded="markResultImageLoaded"
        @invalid="requestMediaRefresh"
        @click="openImagePreview"
      />
      <div
        v-else-if="!job.image_url && isLiveStatus(job.status)"
        class="loading-ritual-panel"
        role="progressbar"
        :aria-valuenow="loadingProgress"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="`生成等待进度 ${loadingProgress}%`"
      >
        <div class="ritual-topline">
          <span class="ritual-kicker">世界调试台</span>
          <span class="ritual-percent">{{ loadingProgress }}%</span>
        </div>
        <p class="ritual-stage">{{ loadingStage }}</p>
        <p class="ritual-main">
          <span>{{ displayedLoadingText }}</span>
          <span v-if="!prefersReducedMotion" class="type-caret" aria-hidden="true" />
        </p>
        <div class="ritual-log-list" aria-label="生成日志">
          <span v-for="(line, index) in visibleLogLines" :key="`${line}-${index}`" :style="{ '--line-index': index }">
            [{{ logIndexLabel(index) }}] {{ line }}
          </span>
        </div>
        <div class="ritual-progress-track" aria-hidden="true">
          <span :style="{ width: `${loadingProgress}%` }" />
        </div>
        <div class="ritual-footer">
          <span>{{ loadingStage }}</span>
          <span>{{ loadingModeText }}</span>
        </div>
      </div>
      <div v-else class="image-placeholder">
        <span>{{ placeholderText(job) }}</span>
      </div>
    </div>


  </section>
</template>
