<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useRouter } from 'vue-router'

import CurrentJobCard from '@/components/CurrentJobCard.vue'
import GalleryGrid from '@/components/GalleryGrid.vue'
import GeneratePanel from '@/components/GeneratePanel.vue'
import PromptModal from '@/components/PromptModal.vue'
import {
  createJob,
  deleteJob,
  fetchGallery,
  fetchJob,
  fetchPublicDiscovery,
  fetchPublicMeta,
  likeGalleryItem,
  toggleJobFavorite,
  toggleJobPublic,
  unlikeGalleryItem,
} from '@/lib/api'
import { isLoggedIn } from '@/lib/auth'
import type {
  BatchCount,
  CreateJobResponse,
  GalleryItem,
  ImageSize,
  JobDetailResponse,
  PublicModel,
  PublicMetaResponse,
} from '@/lib/types'

const ACTIVE_JOB_STORAGE_KEY = 'easy-painter:active-job-ids'

const router = useRouter()

const meta = ref<PublicMetaResponse | null>(null)
const gallery = ref<GalleryItem[]>([])
const publicGallery = ref<GalleryItem[]>([])
const galleryTab = ref<'mine' | 'public'>('public')
const publicSort = ref<'recent' | 'liked'>('recent')
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

const pollingInterval = computed(() => meta.value?.polling_interval_ms ?? 2000)
const availableModels = computed(() => meta.value?.models ?? [])

async function loadMeta() {
  meta.value = await fetchPublicMeta()
  if (!selectedModel.value && meta.value.models.length > 0) {
    selectedModel.value = meta.value.models.find((item) => item.enabled)?.id ?? meta.value.models[0].id
  }
}

async function loadGallery() {
  gallery.value = await fetchGallery()
}

async function loadPublicGallery() {
  publicGallery.value = await fetchPublicDiscovery(publicSort.value)
}

function switchPublicSort(sort: 'recent' | 'liked') {
  publicSort.value = sort
  void loadPublicGallery()
}

function switchGalleryTab(tab: 'mine' | 'public') {
  galleryTab.value = tab
  if (tab === 'public' && publicGallery.value.length === 0) {
    void loadPublicGallery()
  }
}

async function bootstrap() {
  try {
    await loadMeta()
    if (isLoggedIn()) {
      galleryTab.value = 'mine'
      await loadGallery()
    } else {
      galleryTab.value = 'public'
      await loadPublicGallery()
    }
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

function supportsCurrentReferenceInput(model: PublicModel | undefined) {
  return Boolean(model?.enabled) && (!selectedReferenceImage.value || model?.supports_reference_image !== false)
}

function supportsCurrentSize(model: PublicModel | undefined, size: ImageSize) {
  return Boolean(model) && (!model.supported_sizes.length || model.supported_sizes.includes(size))
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

async function handleSettledJob(job: JobDetailResponse) {
  clearJobTimer(job.job_id)
  uncacheJob(job.job_id)
  upsertActiveJob(job)
  if (job.status === 'succeeded') {
    feedback.value = '作品已生成，你可以将其加入画廊。'
    return
  }
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
    } catch {
      feedback.value = '任务状态暂时获取失败，正在继续同步。'
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
  if (!isLoggedIn()) {
    router.push('/login')
    return
  }
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

const displayedGallery = computed(() =>
  galleryTab.value === 'mine' ? gallery.value : publicGallery.value,
)

async function handleDeleteItem(item: GalleryItem) {
  if (!confirm('确定要删除这幅作品吗？')) return
  try {
    await deleteJob(item.job_id)
    gallery.value = gallery.value.filter((g) => g.job_id !== item.job_id)
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '删除失败。'
  }
}

function handleAddToGallery(job: JobDetailResponse) {
  removeActiveJob(job.job_id)
  void loadGallery()
  feedback.value = '作品已加入画廊。'
}

async function handleToggleFavorite(item: GalleryItem) {
  try {
    const result = await toggleJobFavorite(item.job_id)
    item.is_favorite = result.is_favorite
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '操作失败。'
  }
}

async function handleTogglePublic(item: GalleryItem) {
  if (!item.is_public && !confirm('确定将此作品公开到画廊吗？其他用户将可以看到它。')) return
  try {
    const result = await toggleJobPublic(item.job_id)
    item.is_public = result.is_public
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '操作失败。'
  }
}

async function handleToggleLike(item: GalleryItem) {
  try {
    if (item.liked_by_me) {
      await unlikeGalleryItem(item.job_id)
      item.liked_by_me = false
      item.like_count = Math.max(0, (item.like_count ?? 1) - 1)
    } else {
      const result = await likeGalleryItem(item.job_id)
      item.liked_by_me = true
      item.like_count = result.like_count
    }
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '操作失败。'
  }
}

onBeforeUnmount(() => {
  pollingTimers.forEach((timer) => window.clearTimeout(timer))
  pollingTimers.clear()
})

watch([availableModels, selectedReferenceImage], ensureSelectableModel)
watch([availableModels, selectedModel, selectedSize], ensureSelectableSize)

onMounted(() => {
  void bootstrap()
})
</script>

<template>
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
      @add-to-gallery="handleAddToGallery"
    />
  </div>

  <div v-if="loading" class="loading-state">正在加载首页内容…</div>
  <template v-else>
    <div class="gallery-header-row">
      <div class="gallery-tabs" v-if="isLoggedIn()">
        <button
          class="gallery-tab"
          :class="{ active: galleryTab === 'mine' }"
          @click="switchGalleryTab('mine')"
        >我的画廊</button>
        <button
          class="gallery-tab"
          :class="{ active: galleryTab === 'public' }"
          @click="switchGalleryTab('public')"
        >公开画廊</button>
      </div>
      <h2 class="gallery-heading">{{ galleryTab === 'mine' ? '我的画廊' : '公开画廊' }}</h2>
      <div v-if="galleryTab === 'public'" class="gallery-sort-toggle">
        <button
          class="sort-btn"
          :class="{ active: publicSort === 'recent' }"
          @click="switchPublicSort('recent')"
        >最近</button>
        <button
          class="sort-btn"
          :class="{ active: publicSort === 'liked' }"
          @click="switchPublicSort('liked')"
        >最热</button>
      </div>
    </div>
    <GalleryGrid
      :items="displayedGallery"
      :show-username="galleryTab === 'public'"
      :deletable="galleryTab === 'mine'"
      :show-owner-actions="galleryTab === 'mine'"
      :show-likes="galleryTab === 'public'"
      @select="selectedItem = $event"
      @delete="handleDeleteItem"
      @toggle-favorite="handleToggleFavorite"
      @toggle-public="handleTogglePublic"
      @toggle-like="handleToggleLike"
    />
  </template>

  <PromptModal
    :item="selectedItem"
    :is-owner="galleryTab === 'mine'"
    @close="selectedItem = null"
    @toggle-favorite="handleToggleFavorite"
    @toggle-public="handleTogglePublic"
  />
</template>
