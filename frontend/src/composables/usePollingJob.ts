import { onBeforeUnmount, ref } from 'vue'

import { fetchJob } from '@/lib/api'
import type { JobDetailResponse } from '@/lib/types'

export function usePollingJob(onSettled: (job: JobDetailResponse) => void) {
  const currentJob = ref<JobDetailResponse | null>(null)
  const isPolling = ref(false)
  let timer: number | null = null

  function clearPolling() {
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
  }

  async function pollJob(jobId: string, intervalMs: number) {
    clearPolling()
    isPolling.value = true

    const run = async () => {
      try {
        const job = await fetchJob(jobId)
        currentJob.value = job
        if (job.status === 'succeeded' || job.status === 'failed') {
          isPolling.value = false
          clearPolling()
          onSettled(job)
          return
        }
      } catch {
        isPolling.value = false
        clearPolling()
        return
      }

      timer = window.setTimeout(run, intervalMs)
    }

    await run()
  }

  onBeforeUnmount(() => clearPolling())

  return {
    currentJob,
    isPolling,
    pollJob,
    clearPolling,
  }
}
