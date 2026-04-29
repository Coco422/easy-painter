<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppHeader from '@/components/AppHeader.vue'
import CurrentJobCard from '@/components/CurrentJobCard.vue'
import GalleryGrid from '@/components/GalleryGrid.vue'
import GeneratePanel from '@/components/GeneratePanel.vue'
import PromptModal from '@/components/PromptModal.vue'
import { ApiError, createJob, fetchGallery, fetchJob, fetchPublicMeta } from '@/lib/api'
import type {
  BatchCount,
  CreateJobResponse,
  GalleryItem,
  ImageSize,
  JobDetailResponse,
  PublicMetaResponse,
} from '@/lib/types'

const ACTIVE_JOB_STORAGE_KEY = 'easy-painter:active-job-ids'

const meta = ref<PublicMetaResponse | null>(null)
const gallery = ref<GalleryItem[]>([])
const selectedItem = ref<GalleryItem | null>(null)
const prompt = ref('')
const selectedModel = ref('')
const selectedSize = ref<ImageSize>('auto')
const selectedBatchCount = ref<BatchCount>(1)
const selectedReferenceImage = ref<File | null>(null)
const activeJobs = ref<JobDetailResponse[]>([])
const loading = ref(true)
const submitting = ref(false)
const feedback = ref('')
const pollingTimers = new Map<string, number>()
const pollingFailures = new Map<string, number>()

const pollingInterval = computed(() => meta.value?.polling_interval_ms ?? 2000)
const availableModels = computed(() => meta.value?.models ?? [])
const MAX_POLLING_FAILURES = 3

async function loadMeta() {
  meta.value = await fetchPublicMeta()
  if (!selectedModel.value && meta.value.models.length > 0) {
    selectedModel.value = meta.value.models.find((item) => item.enabled)?.id ?? meta.value.models[0].id
  }
}

async function loadGallery() {
  gallery.value = await fetchGallery()
}

async function bootstrap() {
  try {
    await Promise.all([loadMeta(), loadGallery()])
    await restoreCachedJobs()
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '页面初始化失败，请刷新重试。'
  } finally {
    loading.value = false
  }
}

function isLiveJob(job: JobDetailResponse) {
  return job.status === 'queued' || job.status === 'processing'
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
  } catch {
    // Ignore storage failures; polling still works for the current page session.
  }
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
  pollingFailures.delete(jobId)
  uncacheJob(jobId)
  activeJobs.value = activeJobs.value.filter((item) => item.job_id !== jobId)
}

function makeQueuedJob(result: CreateJobResponse, promptText: string, model: string, size: ImageSize): JobDetailResponse {
  return {
    job_id: result.job_id,
    status: result.status,
    image_url: null,
    prompt: promptText,
    revised_prompt: null,
    model,
    size,
    aspect_ratio: null,
    error_message: null,
    created_at: new Date().toISOString(),
    finished_at: null,
  }
}

function markJobFailedLocally(jobId: string, message: string) {
  clearJobTimer(jobId)
  pollingFailures.delete(jobId)
  uncacheJob(jobId)

  const existingJob = activeJobs.value.find((item) => item.job_id === jobId)
  if (!existingJob) return

  upsertActiveJob({
    ...existingJob,
    status: 'failed',
    error_message: message,
    finished_at: existingJob.finished_at ?? new Date().toISOString(),
  })
  feedback.value = message
}

async function handleSettledJob(job: JobDetailResponse) {
  clearJobTimer(job.job_id)
  pollingFailures.delete(job.job_id)
  uncacheJob(job.job_id)

  if (job.status === 'succeeded') {
    activeJobs.value = activeJobs.value.filter((item) => item.job_id !== job.job_id)
    feedback.value = '作品已经完成，已为你刷新画廊。'
    await loadGallery()
    return
  }

  upsertActiveJob(job)
  feedback.value = job.error_message ?? '生成失败，请稍后再试。'
}

function pollJob(jobId: string) {
  clearJobTimer(jobId)

  const run = async () => {
    try {
      const job = await fetchJob(jobId)
      if (!isLiveJob(job)) {
        await handleSettledJob(job)
        return
      }
      upsertActiveJob(job)
      cacheJob(job.job_id)
      pollingFailures.delete(job.job_id)
    } catch (error) {
      const failures = (pollingFailures.get(jobId) ?? 0) + 1
      pollingFailures.set(jobId, failures)

      if (error instanceof ApiError && error.status === 404) {
        markJobFailedLocally(jobId, '任务不存在或已失效，请重新生成。')
        return
      }
      if (failures >= MAX_POLLING_FAILURES) {
        markJobFailedLocally(jobId, '连续获取任务状态失败，请重试或结束。')
        return
      }
      feedback.value = '任务状态暂时获取失败，正在重试同步。'
    }

    pollingTimers.set(jobId, window.setTimeout(run, pollingInterval.value))
  }

  void run()
}

async function restoreCachedJobs() {
  const cachedIds = readCachedJobIds()
  if (cachedIds.length === 0) return

  let restoredCount = 0
  await Promise.all(
    cachedIds.map(async (jobId) => {
      try {
        const job = await fetchJob(jobId)
        if (!isLiveJob(job)) {
          await handleSettledJob(job)
          return
        }
        upsertActiveJob(job)
        cacheJob(job.job_id)
        pollJob(job.job_id)
        restoredCount += 1
      } catch {
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
  referenceImage: File | null
}) {
  const submissions = Array.from({ length: options.batchCount }, () =>
    createJob({
      prompt: options.promptText,
      model: options.model,
      size: options.size,
      reference_image: options.referenceImage,
    }),
  )
  const results = await Promise.allSettled(submissions)
  const fulfilled = results.filter((item): item is PromiseFulfilledResult<CreateJobResponse> => item.status === 'fulfilled')
  const rejected = results.filter((item): item is PromiseRejectedResult => item.status === 'rejected')

  for (const item of fulfilled) {
    const job = makeQueuedJob(item.value, options.promptText, options.model, options.size)
    upsertActiveJob(job)
    cacheJob(job.job_id)
    pollJob(job.job_id)
  }

  if (fulfilled.length === 0) {
    const firstError = rejected[0]?.reason
    throw firstError instanceof Error ? firstError : new Error('提交失败，请稍后重试。')
  }

  const remaining = Math.min(...fulfilled.map((item) => item.value.rate_limit_remaining))
  feedback.value =
    rejected.length > 0
      ? `已提交 ${fulfilled.length} 个任务，${rejected.length} 个任务提交失败。本分钟还可再创建 ${remaining} 次。`
      : `已提交 ${fulfilled.length} 个任务，本分钟还可再创建 ${remaining} 次。`
}

async function submitPrompt() {
  const promptText = prompt.value.trim()
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
      referenceImage: selectedReferenceImage.value,
    })
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

async function retryJob(job: JobDetailResponse) {
  submitting.value = true
  feedback.value = ''
  removeActiveJob(job.job_id)
  prompt.value = job.prompt
  selectedModel.value = job.model
  selectedSize.value = job.size as ImageSize

  try {
    await submitJobs({
      promptText: job.prompt,
      model: job.model,
      size: job.size as ImageSize,
      batchCount: 1,
      referenceImage: selectedReferenceImage.value,
    })
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => {
  pollingTimers.forEach((timer) => window.clearTimeout(timer))
  pollingTimers.clear()
})

onMounted(() => {
  void bootstrap()
})
</script>

<template>
  <div class="page-shell">
    <AppHeader :site-name="meta?.site_name ?? '安落滢绘画站'" />

    <main class="page-content">
      <section class="create-section">
        <GeneratePanel
          :prompt="prompt"
          :selected-model="selectedModel"
          :selected-size="selectedSize"
          :selected-batch-count="selectedBatchCount"
          :reference-image="selectedReferenceImage"
          :models="availableModels"
          :max-length="meta?.prompt_max_length ?? 500"
          :submitting="submitting"
          @update:prompt="prompt = $event"
          @update:model="selectedModel = $event"
          @update:size="selectedSize = $event"
          @update:batch-count="selectedBatchCount = $event"
          @update:reference-image="selectedReferenceImage = $event"
          @submit="submitPrompt"
        />
      </section>

      <p v-if="feedback" class="feedback-banner">{{ feedback }}</p>

      <div v-if="activeJobs.length > 0" class="current-jobs-stack">
        <CurrentJobCard
          v-for="job in activeJobs"
          :key="job.job_id"
          :job="job"
          :is-polling="isLiveJob(job)"
          @retry="retryJob"
          @dismiss="removeActiveJob"
        />
      </div>

      <div v-if="loading" class="loading-state">正在加载首页内容…</div>
      <GalleryGrid v-else :items="gallery" @select="selectedItem = $event" />
    </main>

    <PromptModal :item="selectedItem" @close="selectedItem = null" />
  </div>
</template>
