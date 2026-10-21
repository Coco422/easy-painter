<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { randomId } from '@/lib/browser-crypto'
import { submitGenerationBatch, validGenerationCount } from '@/lib/generation-batch'

import { useRoute, useRouter } from 'vue-router'

import ArtworkModal from '@/components/ArtworkModal.vue'
import { fetchArtwork, type Artwork } from '@/lib/artworks'
import CurrentJobBatch from '@/components/CurrentJobBatch.vue'
import { groupJobs } from '@/lib/job-batches'
import GeneratePanel from '@/components/GeneratePanel.vue'
import CreationVersions from '@/components/CreationVersions.vue'
import { useCreationVersions } from '@/composables/useCreationVersions'
import { ArrowUpRight, FlaskConical, Image, Layers, LayoutTemplate, Package, Palette, Workflow } from 'lucide-vue-next'
import { creationTemplates, type CreationMode } from '@/lib/creation-presets'
import { useReferenceImages } from '@/composables/useReferenceImages'
import {
  ApiError,
  createJob,
  fetchActiveJobs,
  fetchJob,
  fetchPublicMeta,
} from '@/lib/api'
import { authState, fetchCurrentUser, isLoggedIn } from '@/lib/auth'
import type {
  BatchCount,
  CreateJobResponse,
  ImageSize,
  JobDetailResponse,
  PublicModel,
  PublicMetaResponse,
} from '@/lib/types'

const BATCH_STORAGE_KEY = 'easy-painter:job-batches'
const jobBatches = ref<Record<string, string>>(readJobBatches())
const activeBatches = computed(() => groupJobs(activeJobs.value, jobBatches.value))

function readJobBatches(): Record<string, string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(BATCH_STORAGE_KEY) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))
  } catch { return {} }
}

function saveJobBatches() {
  const retainedIds = new Set([...readCachedJobIds(), ...activeJobs.value.map(job => job.job_id)])
  jobBatches.value = Object.fromEntries(Object.entries(jobBatches.value).filter(([id]) => retainedIds.has(id)))
  try { window.localStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify(jobBatches.value)) } catch {}
}

const ACTIVE_JOB_STORAGE_KEY = 'easy-painter:active-job-ids'

const router = useRouter()
const route = useRoute()

const meta = ref<PublicMetaResponse | null>(null)
const prompt = ref('')
const mode = ref<CreationMode>('text')
const generatePanel = ref<InstanceType<typeof GeneratePanel> | null>(null)
const resultsPanel = ref<HTMLElement | null>(null)
const templateIcons = { free: Palette, workflow: Workflow, mechanism: FlaskConical, poster: LayoutTemplate, product: Package }
const referenceIds = computed(() => mode.value === 'text' ? [] : selectedReferenceImage.value.map(item => item.id))
const pendingCount = computed(() => activeJobs.value.filter(isLiveJob).length)
const selectedModel = ref('')
const selectedSize = ref<ImageSize>('auto')
const selectedBatchCount = ref<BatchCount>(1)
const { selected: selectedReferenceImage } = useReferenceImages()
const selectedArtwork = ref<Artwork | null>(null)
const artworkAction = ref<'gallery' | undefined>()
const activeJobs = ref<JobDetailResponse[]>([])
const loading = ref(true)
const submitting = ref(false)
const stopBatchRequested = ref(false)
const feedback = ref('')
const pollingTimers = new Map<string, number>()

const pollingInterval = computed(() => meta.value?.polling_interval_ms ?? 2000)
const availableModels = computed(() => meta.value?.models ?? [])
const versions = useCreationVersions({
  jobs: activeJobs, membership: jobBatches, models: availableModels, selectedModel, selectedSize,
  maxLength: computed(() => meta.value?.prompt_max_length ?? 4000), feedback,
  register(result, request) {
    const job = makeQueuedJob(result, request.prompt, request.model, request.size)
    jobBatches.value[job.job_id] = randomId()
    upsertActiveJob(job)
    cacheJob(job.job_id)
    pollJob(job.job_id)
    saveJobBatches()
    void scrollToResults()
  },
  restore(job) { if (isLiveJob(job)) restoreLiveJob(job); else upsertActiveJob(job) },
})
let pageEpoch = 0

async function scrollToResults() {
  await nextTick()
  resultsPanel.value?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}

async function loadMeta() {
  meta.value = await fetchPublicMeta()
  if (!selectedModel.value && meta.value.models.length > 0) {
    selectedModel.value = meta.value.models.find((item) => item.enabled)?.id ?? meta.value.models[0].id
  }
}

function isLiveJob(job: JobDetailResponse) {
  return job.status === 'queued' || job.status === 'processing'
}

async function refreshJobMedia(job: JobDetailResponse) {
  try {
    const refreshed = await fetchJob(job.job_id)
    const index = activeJobs.value.findIndex((item) => item.job_id === job.job_id)
    if (index >= 0) activeJobs.value.splice(index, 1, refreshed)
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '图片链接刷新失败。'
  }
}

function supportsCurrentReferenceInput(model: PublicModel | undefined) {
  return Boolean(model?.enabled) && (mode.value === 'text' || model?.supports_reference_image !== false)
}

function supportsCurrentSize(model: PublicModel | undefined, size: ImageSize) {
  return Boolean(model && (!model.supported_sizes.length || model.supported_sizes.includes(size)))
}

function ensureSelectableModel() {
  const currentModel = availableModels.value.find((item) => item.id === selectedModel.value)
  if (supportsCurrentReferenceInput(currentModel)) return
  selectedModel.value = availableModels.value.find((item) => supportsCurrentReferenceInput(item))?.id ?? ''
}

function ensureSelectableSize() {
  const currentModel = availableModels.value.find((item) => item.id === selectedModel.value)
  if (!currentModel || supportsCurrentSize(currentModel, selectedSize.value)) return
  selectedSize.value = (currentModel.supported_sizes[0] as ImageSize | undefined) ?? 'auto'
}

function readCachedJobIds() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(ACTIVE_JOB_STORAGE_KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function writeCachedJobIds(jobIds: string[]) {
  try {
    const uniqueIds = [...new Set(jobIds)]
    if (uniqueIds.length === 0) {
      window.localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY)
      return
    }
    window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, JSON.stringify(uniqueIds))
  } catch {}
}

function cacheJob(jobId: string) {
  writeCachedJobIds([...readCachedJobIds(), jobId])
}

function uncacheJob(jobId: string) {
  writeCachedJobIds(readCachedJobIds().filter((item) => item !== jobId))
}

function upsertActiveJob(job: JobDetailResponse) {
  const index = activeJobs.value.findIndex((item) => item.job_id === job.job_id)
  if (index >= 0) {
    activeJobs.value.splice(index, 1, job)
  } else {
    activeJobs.value.unshift(job)
  }
  versions.record(job.job_id)
}

function clearJobTimer(jobId: string) {
  const timer = pollingTimers.get(jobId)
  if (timer !== undefined) {
    window.clearTimeout(timer)
    pollingTimers.delete(jobId)
  }
}

function removeActiveJob(jobId: string) {
  clearJobTimer(jobId)
  uncacheJob(jobId)
  activeJobs.value = activeJobs.value.filter((item) => item.job_id !== jobId)
  versions.forget(jobId)
  saveJobBatches()
}

function makeQueuedJob(result: CreateJobResponse, promptText: string, model: string, size: ImageSize): JobDetailResponse {
  const modelConfig = availableModels.value.find((item) => item.id === model)
  return {
    job_id: result.job_id,
    status: result.status,
    image_url: null,
    prompt: promptText,
    revised_prompt: null,
    model,
    model_label: modelConfig?.label ?? model,
    provider_name: null,
    size,
    aspect_ratio: null,
    error_message: null,
    credit_cost: result.credit_cost,
    billing_status: result.billing_status,
    refunded_at: null,
    created_at: new Date().toISOString(),
    finished_at: null,
  }
}

async function handleSettledJob(job: JobDetailResponse) {
  const epoch = pageEpoch
  clearJobTimer(job.job_id)
  uncacheJob(job.job_id)
  upsertActiveJob(job)
  await fetchCurrentUser().catch(() => undefined)
  if (epoch !== pageEpoch) return
  if (job.status === 'succeeded') {
    feedback.value = '作品已生成，你可以将其加入画廊。'
    return
  }
  feedback.value = job.billing_status === 'refunded'
    ? `${job.error_message ?? '生成失败。'} 已全额退回 ${job.credit_cost} 丝。`
    : job.error_message ?? '生成失败，请稍后再试。'
}

function pollJob(jobId: string) {
  clearJobTimer(jobId)
  const epoch = pageEpoch
  const run = async () => {
    try {
      const job = await fetchJob(jobId)
      if (epoch !== pageEpoch) return
      if (!isLiveJob(job)) {
        await handleSettledJob(job)
        return
      }
      upsertActiveJob(job)
      cacheJob(job.job_id)
    } catch {
      if (epoch !== pageEpoch) return
      feedback.value = '任务状态暂时获取失败，正在继续同步。'
    }
    if (epoch !== pageEpoch) return
    pollingTimers.set(jobId, window.setTimeout(run, pollingInterval.value))
  }
  void run()
}

function restoreLiveJob(job: JobDetailResponse) {
  upsertActiveJob(job)
  cacheJob(job.job_id)
  pollJob(job.job_id)
}

async function restoreCachedJobs() {
  const epoch = pageEpoch
  const serverJobIds = new Set<string>()
  let restoredCount = 0

  if (isLoggedIn()) {
    try {
      const serverJobs = await fetchActiveJobs()
      if (epoch !== pageEpoch) return
      for (const job of serverJobs) {
        serverJobIds.add(job.job_id)
        if (isLiveJob(job)) {
          restoreLiveJob(job)
          restoredCount += 1
        }
      }
    } catch {
      feedback.value = '进行中任务暂时无法从后端同步，正在尝试本地缓存。'
    }
  }

  const cachedIds = readCachedJobIds()
  if (cachedIds.length === 0 && restoredCount === 0) return
  await Promise.all(
    cachedIds.filter((jobId) => !serverJobIds.has(jobId)).map(async (jobId) => {
      try {
        const job = await fetchJob(jobId)
        if (epoch !== pageEpoch) return
        if (!isLiveJob(job)) {
          await handleSettledJob(job)
          return
        }
        restoreLiveJob(job)
        restoredCount += 1
      } catch {
        if (epoch !== pageEpoch) return
        uncacheJob(jobId)
      }
    }),
  )
  if (restoredCount > 0) {
    feedback.value = `已恢复 ${restoredCount} 个进行中的任务。`
  }
}

async function submitJobs(options: {
  promptText: string
  model: string
  size: ImageSize
  batchCount: BatchCount
  referenceImageIds: string[]
}) {
  const epoch = pageEpoch
  const model = availableModels.value.find((item) => item.id === options.model)
  if (options.referenceImageIds.length > (model?.max_reference_images ?? 5)) {
    throw new Error(`当前模型单次最多支持 ${model?.max_reference_images ?? 5} 张参考图，请移除多余图片。`)
  }
  if (!validGenerationCount(options.batchCount)) throw new Error('生成数量需为正整数。')
  const batchId = randomId()
  stopBatchRequested.value = false
  let first = true
  const summary = await submitGenerationBatch(options.batchCount, async () => {
    const idempotencyKey = randomId()
    const payload = {
      prompt: options.promptText,
      model: options.model,
      size: options.size,
      reference_image_ids: options.referenceImageIds,
    }
    const submit = () => createJob(payload, idempotencyKey)
    return submit().catch((error) => {
      if (error instanceof ApiError || epoch !== pageEpoch) throw error
      // A lost response must reuse the same intent and request parameters.
      return submit()
    })
  }, {
    isCurrent: () => epoch === pageEpoch,
    shouldContinue: () => !stopBatchRequested.value,
    onSuccess(result) {
      jobBatches.value[result.job_id] = batchId
      const job = makeQueuedJob(result, options.promptText, options.model, options.size)
      upsertActiveJob(job)
      cacheJob(job.job_id)
      pollJob(job.job_id)
      if (first) { versions.selectedId.value = job.job_id; first = false; void scrollToResults() }
    },
    onProgress(completed) { feedback.value = `正在提交 ${completed} / ${options.batchCount} 张…` },
  })
  if (epoch !== pageEpoch) throw new Error('登录状态已变化，请重新打开创作台。')
  saveJobBatches()
  await fetchCurrentUser().catch(() => undefined)
  if (epoch !== pageEpoch) return
  if (summary.accepted === 0 && summary.error) throw summary.error
  const stopped = summary.remaining > 0 ? `其余 ${summary.remaining} 张尚未提交。` : ''
  feedback.value = `已提交 ${summary.accepted} 个任务，实际预扣 ${summary.reserved} 丝。` +
    (summary.failed ? ` ${summary.failed} 个请求未确认成功。${summary.error?.message ?? ''}` : '') + stopped
  void scrollToResults()
}

async function submitPrompt(promptText: string) {
  if (submitting.value || versions.busy.value) return
  if (!isLoggedIn()) {
    router.push('/login')
    return
  }
  if (!promptText) {
    feedback.value = '先写下一句你想看到的画面吧。'
    return
  }
  submitting.value = true
  feedback.value = ''
  try {
    await submitJobs({
      promptText,
      model: selectedModel.value,
      size: selectedSize.value,
      batchCount: selectedBatchCount.value,
      referenceImageIds: referenceIds.value,
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 402) {
      feedback.value = `灵感丝线不足（需要 ${error.required ?? '?'} 丝，当前 ${error.balance ?? 0} 丝）。前往个人中心兑换 →`
      router.push('/profile')
      return
    }
    feedback.value = error instanceof Error ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

async function retryJob(job: JobDetailResponse) {
  if (submitting.value || versions.busy.value) return
  if (versions.history.value.parents[job.job_id]) { await versions.retryRevision(job); return }
  submitting.value = true
  feedback.value = ''
  selectedModel.value = job.model
  selectedSize.value = job.size as ImageSize
  try {
    await submitJobs({
      promptText: job.prompt,
      model: job.model,
      size: job.size as ImageSize,
      batchCount: 1,
      referenceImageIds: referenceIds.value,
    })
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

async function openArtwork(job: JobDetailResponse, action?: 'gallery') {
  const epoch = pageEpoch
  try {
    const artwork = await fetchArtwork('job', job.job_id)
    if (epoch !== pageEpoch) return
    selectedArtwork.value = artwork
    artworkAction.value = action
  } catch (error) { if (epoch === pageEpoch) feedback.value = error instanceof Error ? error.message : '作品读取失败。' }
}
function handleAddToGallery(job: JobDetailResponse) { void openArtwork(job, 'gallery') }

async function bootstrap() {
  const epoch = pageEpoch
  try {
    await loadMeta()
    if (epoch !== pageEpoch) return
    if (typeof route.query.prompt === 'string' && route.query.prompt.trim()) {
      prompt.value = route.query.prompt.trim()
    }
    if (isLoggedIn()) {
      await fetchCurrentUser()
      if (epoch !== pageEpoch) return
      await versions.load()
      if (epoch !== pageEpoch) return
      await restoreCachedJobs()
    }
  } catch (error) {
    if (epoch !== pageEpoch) return
    feedback.value = error instanceof Error ? error.message : '页面初始化失败，请刷新重试。'
  } finally {
    if (epoch === pageEpoch) loading.value = false
  }
}

watch(() => route.query.prompt, (val) => {
  if (typeof val === 'string' && val.trim()) {
    prompt.value = val.trim()
  }
})

watch(selectedReferenceImage, (images, previous) => {
  if (mode.value === 'text' && images.some(item => !previous.some(entry => entry.id === item.id))) mode.value = 'reference'
})
watch([availableModels, mode], ensureSelectableModel)
watch([availableModels, selectedModel, selectedSize], ensureSelectableSize)
watch(() => authState.sessionId, () => {
  pageEpoch++
  pollingTimers.forEach(timer => window.clearTimeout(timer))
  pollingTimers.clear()
  activeJobs.value = []
  selectedArtwork.value = null
  feedback.value = ''
  submitting.value = false
  if (isLoggedIn()) void bootstrap()
})

onBeforeUnmount(() => {
  pageEpoch++
  pollingTimers.forEach((timer) => window.clearTimeout(timer))
  pollingTimers.clear()
})

onMounted(() => {
  void bootstrap()
})
</script>

<template>
  <section class="creation-workspace">
    <header class="workspace-heading">
      <div><p class="section-label">Painter's studio</p><h1>创作工作台</h1><p>从一个想法、一张参考图开始。</p></div>
      <div class="workspace-heading-actions"><button v-if="activeJobs.length" type="button" class="workspace-results-jump" @click="scrollToResults">查看作品</button><router-link to="/canvas" class="workspace-canvas-link"><Layers :size="16" aria-hidden="true" />无限画布<ArrowUpRight :size="15" aria-hidden="true" /></router-link></div>
    </header>
    <div class="workspace-columns">
    <aside class="workspace-settings" aria-label="创作设置">
    <GeneratePanel
      ref="generatePanel"
      :prompt="prompt"
      :mode="mode"
      :selected-model="selectedModel"
      :selected-size="selectedSize"
      :selected-batch-count="selectedBatchCount"
      :models="availableModels"
      :max-length="meta?.prompt_max_length ?? 4000"
      :submitting="submitting || versions.busy.value"
      :credits="isLoggedIn() ? (authState.user?.credits ?? 0) : null"
      @update:prompt="prompt = $event"
      @update:mode="mode = $event"
      @update:model="selectedModel = $event"
      @update:size="selectedSize = $event"
      @update:batch-count="selectedBatchCount = $event"
      @submit="submitPrompt"
    />
    <button v-if="submitting" type="button" class="ghost-button" :disabled="stopBatchRequested" @click="stopBatchRequested = true">{{ stopBatchRequested ? '正在停止继续提交…' : '停止继续提交' }}</button>
    </aside>

    <section ref="resultsPanel" class="workspace-results" aria-label="创作结果" :aria-busy="loading">
      <div class="workspace-results-heading"><h2>{{ activeJobs.length ? '本次创作' : '让想法有个起点' }}</h2><span v-if="pendingCount" role="status">{{ pendingCount }} 张生成中</span><router-link v-else-if="isLoggedIn()" to="/history">查看历史<ArrowUpRight :size="14" aria-hidden="true" /></router-link></div>
      <p v-if="feedback" class="feedback-banner" role="status">{{ feedback }}</p>
      <p v-if="versions.storageError.value" class="feedback-banner" role="alert">{{ versions.storageError.value }}</p>
      <div v-if="!activeJobs.length && versions.history.value.pending" class="feedback-banner" role="status">上次改图的提交结果尚未确认。<button type="button" class="ghost-button" :disabled="versions.busy.value" @click="versions.confirm">确认上次改图任务</button></div>

      <ArtworkModal v-if="selectedArtwork" :key="selectedArtwork.id" :item="selectedArtwork" :initial-action="artworkAction" @close="selectedArtwork = null" @updated="selectedArtwork = $event" @deleted="removeActiveJob($event.id)" />
      <CreationVersions v-if="activeJobs.length" :jobs="activeJobs" :membership="jobBatches" :parents="versions.history.value.parents" :selected-id="versions.selectedId.value" :busy="submitting || versions.busy.value" :pending="!!versions.history.value.pending" :edit-model="versions.editModel.value?.label ?? ''" :edit-cost="versions.editModel.value?.credit_cost ?? 0" :edit-size="versions.editSize.value" :max-length="meta?.prompt_max_length ?? 4000" :canvases="versions.canvases.value"
        @select="versions.selectedId.value = $event" @revise="versions.revise" @confirm="versions.confirm" @canvas="versions.addToCanvas" @details="openArtwork($event)" @gallery="handleAddToGallery" @refresh="refreshJobMedia" />
      <details v-if="activeJobs.length" class="workspace-task-details" :open="pendingCount > 0"><summary>任务详情与计费 · {{ activeJobs.length }} 张</summary>
      <div class="current-jobs-stack">
    <CurrentJobBatch
      v-for="batch in activeBatches"
      :key="batch.id"
      :jobs="batch.jobs"
      @retry="retryJob"
      @dismiss="removeActiveJob"
      @add-to-gallery="handleAddToGallery"
      @details="openArtwork($event)"
      @refresh-media="refreshJobMedia"
    />
      </div>
      </details>
      <div v-if="!activeJobs.length" class="workspace-empty">
        <div class="workspace-intro"><span class="workspace-intro-icon"><Image :size="28" aria-hidden="true" /></span><h3>这次想创作什么？</h3><p>选一个用途带入示例，或直接写下你的想法。<br />生成的作品会显示在这里。</p></div>
        <div class="workspace-templates">
          <button v-for="item in creationTemplates.filter(item => item.id !== 'free')" :key="item.id" type="button" :disabled="submitting" @click="mode === 'edit' && (mode = 'text'); generatePanel?.applyTemplate(item.id)">
            <component :is="templateIcons[item.id]" :size="22" aria-hidden="true" /><strong>{{ item.label }}</strong><span>{{ item.detail }}</span><ArrowUpRight :size="15" class="template-arrow" aria-hidden="true" />
          </button>
        </div>
        <p class="workspace-empty-note">模板帮助组织描述。模型与费用可以在左侧查看，科研内容请核对细节。</p>
      </div>
    </section>
    </div>
  </section>
</template>

<style scoped>
.creation-workspace { font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; }
.workspace-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; }
.workspace-heading .section-label { margin: 0 0 8px; font-size: 11px; font-weight: 500; }
.workspace-heading h1 { margin: 0; font-size: 26px; font-weight: 500; line-height: 1.3; }
.workspace-heading p:last-child { margin: 8px 0 0; color: var(--text-secondary); font-size: 13px; }
.workspace-canvas-link { display: inline-flex; align-items: center; gap: 8px; color: var(--text-secondary); text-decoration: none; font-size: 13px; white-space: nowrap; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; }
.workspace-canvas-link:hover { color: var(--accent-strong); border-color: var(--border-accent); }
.workspace-heading-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.workspace-results-jump { display: none; border: 0; background: transparent; color: var(--accent-strong); font: inherit; font-size: 12px; padding: 8px 0; cursor: pointer; }
.workspace-columns { display: grid; grid-template-columns: 340px minmax(0, 1fr); align-items: start; gap: 24px; }
.workspace-settings, .workspace-results { min-width: 0; }
.workspace-results { padding: 24px; min-height: 650px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg-surface); scroll-margin-top: 16px; }
.workspace-results-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
.workspace-results-heading h2 { font-size: 15px; font-weight: 500; margin: 0; }
.workspace-results-heading > span, .workspace-results-heading a { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-secondary); text-decoration: none; }
.workspace-results .feedback-banner { margin: 16px 0 0; padding: 12px; font-size: 13px; border-radius: 6px; background: var(--bg-input); overflow-wrap: anywhere; }
.workspace-intro { text-align: center; padding: 48px 0 32px; }
.workspace-intro-icon { display: inline-flex; align-items: center; justify-content: center; width: 56px; height: 56px; border-radius: 12px; background: var(--accent-soft); color: var(--accent-strong); }
.workspace-intro h3 { font-size: 22px; font-weight: 500; margin: 20px 0 12px; }
.workspace-intro p { color: var(--text-secondary); font-size: 13px; line-height: 1.8; margin: 0; }
.workspace-templates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.workspace-templates button { position: relative; display: flex; flex-direction: column; align-items: flex-start; gap: 10px; min-width: 0; padding: 20px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; color: var(--accent-strong); text-align: left; font: inherit; cursor: pointer; transition: background 160ms, border-color 160ms; }
.workspace-templates button:hover { background: var(--bg-elevated); border-color: var(--border-accent); }
.workspace-templates button:focus-visible, .workspace-canvas-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.workspace-templates strong { color: var(--text-primary); font-size: 14px; font-weight: 500; }
.workspace-templates span { color: var(--text-secondary); font-size: 12px; }
.workspace-templates .template-arrow { position: absolute; right: 16px; top: 20px; color: var(--text-muted); }
.workspace-empty-note { margin: 24px 0 0; font-size: 12px; color: var(--text-secondary); line-height: 1.8; }
.workspace-results .current-jobs-stack { margin-top: 20px; }
.workspace-task-details { margin-top: 24px; border-top: 1px solid var(--border); padding-top: 16px; }
.workspace-task-details > summary { cursor: pointer; font-size: 13px; color: var(--text-secondary); }
.workspace-results :deep(.current-job-batch) { padding: 0 0 20px; background: transparent; border: 0; border-bottom: 1px solid var(--border); border-radius: 0; }
.workspace-results :deep(.current-job-batch:last-child) { border-bottom: 0; padding-bottom: 0; }
.workspace-results :deep(.batch-job-grid:has(> :only-child)) { grid-template-columns: minmax(0, 1fr); }
.workspace-results :deep(.batch-job-item) { border-radius: 6px; }
@media (max-width: 1050px) { .workspace-columns { grid-template-columns: 310px minmax(0, 1fr); gap: 16px; } .workspace-results { padding: 20px; } .workspace-templates button { padding: 16px; } }
@media (max-width: 900px) { .workspace-columns { grid-template-columns: minmax(0, 1fr); } .workspace-results { min-height: 0; } .workspace-heading { margin-bottom: 20px; } .workspace-intro { padding-top: 24px; } }
@media (max-width: 900px) { .workspace-results-jump { display: block; } }
@media (max-width: 450px) { .workspace-heading h1 { font-size: 22px; } .workspace-canvas-link { gap: 4px; padding: 8px; font-size: 12px; } .workspace-results { padding: 16px; } .workspace-templates { grid-template-columns: minmax(0, 1fr); } .workspace-heading .section-label { letter-spacing: .06em; } }
</style>
