<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppHeader from '@/components/AppHeader.vue'
import CurrentJobCard from '@/components/CurrentJobCard.vue'
import GalleryGrid from '@/components/GalleryGrid.vue'
import GeneratePanel from '@/components/GeneratePanel.vue'
import PromptModal from '@/components/PromptModal.vue'
import { usePollingJob } from '@/composables/usePollingJob'
import { createJob, fetchGallery, fetchPublicMeta } from '@/lib/api'
import type { GalleryItem, PublicMetaResponse } from '@/lib/types'

const meta = ref<PublicMetaResponse | null>(null)
const gallery = ref<GalleryItem[]>([])
const selectedItem = ref<GalleryItem | null>(null)
const prompt = ref('')
const selectedModel = ref('')
const selectedAspectRatio = ref<'auto' | '1:1' | '3:4' | '9:16' | '4:3' | '16:9'>('auto')
const loading = ref(true)
const submitting = ref(false)
const feedback = ref('')

const { currentJob, isPolling, pollJob } = usePollingJob(async (job) => {
  if (job.status === 'succeeded') {
    feedback.value = '作品已经完成，已为你刷新画廊。'
    await loadGallery()
  } else if (job.status === 'failed') {
    feedback.value = job.error_message ?? '生成失败，请稍后再试。'
  }
})

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

async function bootstrap() {
  try {
    await Promise.all([loadMeta(), loadGallery()])
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '页面初始化失败，请刷新重试。'
  } finally {
    loading.value = false
  }
}

async function submitPrompt() {
  if (!prompt.value.trim()) {
    feedback.value = '先写下一句你想看到的画面吧。'
    return
  }

  submitting.value = true
  feedback.value = ''

  try {
    const result = await createJob({
      prompt: prompt.value.trim(),
      model: selectedModel.value,
      aspect_ratio: selectedAspectRatio.value,
    })
    feedback.value =
      result.rate_limit_remaining > 0
        ? `任务已提交，本分钟还可再创建 ${result.rate_limit_remaining} 次。`
        : '任务已提交，本分钟额度已用完。'
    await pollJob(result.job_id, meta.value?.polling_interval_ms ?? 2000)
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

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
          :selected-aspect-ratio="selectedAspectRatio"
          :models="availableModels"
          :max-length="meta?.prompt_max_length ?? 500"
          :submitting="submitting"
          @update:prompt="prompt = $event"
          @update:model="selectedModel = $event"
          @update:aspect-ratio="selectedAspectRatio = $event"
          @submit="submitPrompt"
        />
      </section>

      <p v-if="feedback" class="feedback-banner">{{ feedback }}</p>

      <CurrentJobCard :job="currentJob" :is-polling="isPolling" />

      <div v-if="loading" class="loading-state">正在加载首页内容…</div>
      <GalleryGrid v-else :items="gallery" @select="selectedItem = $event" />
    </main>

    <PromptModal :item="selectedItem" @close="selectedItem = null" />
  </div>
</template>
