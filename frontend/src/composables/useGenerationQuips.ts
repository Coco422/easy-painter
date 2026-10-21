import { shallowRef, watch, type Ref } from 'vue'
import { useMediaClock } from './useMediaClock'
import { nextGenerationQuip, type GenerationQuip } from '@/lib/generation-quips'

export function useGenerationQuips(jobs: Ref<readonly { job_id: string; status: string }[]>, random: () => number = Math.random) {
  const now = useMediaClock()
  const quips = shallowRef(new Map<string, GenerationQuip>())
  watch([() => jobs.value.filter(job => job.status === 'queued' || job.status === 'processing').map(job => job.job_id), now], ([ids, time]) => {
    const next = new Map<string, GenerationQuip>()
    let changed = ids.length !== quips.value.size
    for (const id of ids) {
      const previous = quips.value.get(id)
      const value = previous && time < previous.nextAt ? previous : nextGenerationQuip(time, previous, random)
      next.set(id, value)
      changed ||= value !== previous
    }
    if (changed) quips.value = next
  }, { immediate: true })
  return quips
}
