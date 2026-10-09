<script setup lang="ts">
import { computed } from 'vue'
import CurrentJobCard from './CurrentJobCard.vue'
import type { JobDetailResponse } from '@/lib/types'

const props = defineProps<{ jobs: JobDetailResponse[] }>()
const emit = defineEmits<{
  retry: [job: JobDetailResponse]
  dismiss: [jobId: string]
  addToGallery: [job: JobDetailResponse]
  refreshMedia: [job: JobDetailResponse]
  details: [job: JobDetailResponse]
}>()
const first = computed(() => props.jobs[0])
const completed = computed(() => props.jobs.filter(job => job.status === 'succeeded').length)
const failed = computed(() => props.jobs.filter(job => job.status === 'failed').length)
const pending = computed(() => props.jobs.length - completed.value - failed.value)
function isLive(job: JobDetailResponse) { return job.status === 'queued' || job.status === 'processing' }
</script>

<template>
  <section v-if="first" class="current-job-batch">
    <div class="batch-heading">
      <strong>{{ jobs.length > 1 ? `本批生成 ${jobs.length} 张` : '当前任务' }}</strong>
      <span v-if="pending" class="status-dot" aria-hidden="true" />
      <span role="status">已生成 {{ completed }} / {{ jobs.length }} 张<span v-if="pending"> · {{ pending }} 张等待中</span><span v-if="failed"> · {{ failed }} 张失败</span></span>
    </div>
    <details class="job-prompt-details">
      <summary class="job-prompt">{{ first.prompt }}</summary>
      <p class="job-prompt-full">{{ first.prompt }}</p>
    </details>
    <p class="job-billing-meta">{{ first.model_label || first.model }} · {{ first.size }} · {{ first.credit_cost }} 丝 / 张</p>
    <div class="batch-job-grid">
      <div v-for="(job, index) in jobs" :key="job.job_id" class="batch-job-item" :class="{ 'batch-job-item--live': isLive(job) }">
        <span class="batch-job-number">第 {{ index + 1 }} 张</span>
        <CurrentJobCard :job="job" :is-polling="isLive(job)" compact
          @retry="emit('retry', $event)" @dismiss="emit('dismiss', $event)"
          @add-to-gallery="emit('addToGallery', $event)" @details="emit('details', $event)"
          @refresh-media="emit('refreshMedia', $event)" />
      </div>
    </div>
  </section>
</template>
