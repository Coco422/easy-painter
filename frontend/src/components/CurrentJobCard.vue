<script setup lang="ts">
import type { JobDetailResponse } from '@/lib/types'

const props = defineProps<{
  job: JobDetailResponse | null
  isPolling: boolean
}>()

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
</script>

<template>
  <section v-if="job" class="current-job">
    <div class="current-job-copy">
      <p class="section-label">当前任务</p>
      <div class="status-line">
        <strong>{{ statusText(job.status) }}</strong>
        <span v-if="isPolling" class="status-dot" />
      </div>
      <p class="job-prompt">{{ job.prompt }}</p>
      <p v-if="job.error_message" class="job-error">{{ job.error_message }}</p>
    </div>

    <div class="current-job-visual">
      <img v-if="job.image_url" :src="job.image_url" alt="当前任务结果图" />
      <div v-else class="image-placeholder">
        <span>{{ job.status === 'failed' ? '请稍后再试' : '异步创作中' }}</span>
      </div>
    </div>
  </section>
</template>
