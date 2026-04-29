<script setup lang="ts">
import type { JobDetailResponse } from '@/lib/types'

const props = defineProps<{
  job: JobDetailResponse | null
  isPolling: boolean
}>()

const emit = defineEmits<{
  retry: [job: JobDetailResponse]
  dismiss: [jobId: string]
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

function placeholderText(job: JobDetailResponse) {
  if (job.status === 'failed') return '生成失败'
  if (job.status === 'queued') return '等待执行'
  return '异步创作中'
}
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
      <p v-if="job.status === 'failed'" class="job-error">{{ job.error_message || '任务已失败，请重试或结束。' }}</p>
      <div v-if="job.status === 'failed'" class="current-job-actions">
        <button type="button" class="secondary-button" @click="emit('retry', job)">重新生成</button>
        <button type="button" class="ghost-button" @click="emit('dismiss', job.job_id)">结束</button>
      </div>
    </div>

    <div class="current-job-visual">
      <img v-if="job.image_url" :src="job.image_url" alt="当前任务结果图" />
      <div v-else class="image-placeholder">
        <span>{{ placeholderText(job) }}</span>
      </div>
    </div>
  </section>
</template>
