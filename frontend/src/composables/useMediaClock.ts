import { onBeforeUnmount, onMounted, ref } from 'vue'

const now = ref(Date.now())
let serverOffset = 0
let consumers = 0
let timer: ReturnType<typeof setInterval> | undefined
export function syncMediaClock(serverTime: string) {
  const parsed = Date.parse(serverTime)
  if (Number.isFinite(parsed)) serverOffset = parsed - Date.now()
  now.value = Date.now() + serverOffset
}
export function useMediaClock() {
  onMounted(() => {
    consumers += 1
    now.value = Date.now() + serverOffset
    if (!timer) timer = setInterval(() => { now.value = Date.now() + serverOffset }, 1000)
  })
  onBeforeUnmount(() => {
    consumers -= 1
    if (consumers === 0 && timer) { clearInterval(timer); timer = undefined }
  })
  return now
}
