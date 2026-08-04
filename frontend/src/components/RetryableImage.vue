<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    src: string
    alt?: string
    retryDelays?: number[]
    resetKey?: string | number
  }>(),
  {
    alt: '',
    retryDelays: () => [1500, 5000, 15000, 30000],
    resetKey: 0,
  },
)

const emit = defineEmits<{
  load: [event: Event]
  failed: []
  retryScheduled: [attempt: number, delayMs: number]
}>()

const loaded = ref(false)
const failed = ref(false)
const retrying = ref(false)
const retryCount = ref(0)
const requestVersion = ref(0)
let retryTimer: number | undefined

const imageKey = computed(() => `${props.src}:${requestVersion.value}`)
const maxRetries = computed(() => props.retryDelays.length)

function clearRetryTimer() {
  if (retryTimer === undefined) return
  window.clearTimeout(retryTimer)
  retryTimer = undefined
}

function resetState() {
  clearRetryTimer()
  loaded.value = false
  failed.value = false
  retrying.value = false
  retryCount.value = 0
  requestVersion.value = 0
}

function retryNow() {
  clearRetryTimer()
  loaded.value = false
  failed.value = false
  retrying.value = true
  retryCount.value = 0
  requestVersion.value += 1
}

function handleLoad(event: Event) {
  clearRetryTimer()
  loaded.value = true
  failed.value = false
  retrying.value = false
  retryCount.value = 0
  emit('load', event)
}

function handleError() {
  loaded.value = false

  const baseDelay = props.retryDelays[retryCount.value]
  if (baseDelay === undefined) {
    retrying.value = false
    failed.value = true
    emit('failed')
    return
  }

  const attempt = retryCount.value + 1
  const delayMs = Math.max(0, Math.round(baseDelay * (0.85 + Math.random() * 0.3)))
  retryCount.value = attempt
  retrying.value = true
  failed.value = false
  emit('retryScheduled', attempt, delayMs)

  clearRetryTimer()
  retryTimer = window.setTimeout(() => {
    retryTimer = undefined
    requestVersion.value += 1
  }, delayMs)
}

watch(
  () => props.src,
  () => resetState(),
)

watch(
  () => props.resetKey,
  () => retryNow(),
)

onBeforeUnmount(() => clearRetryTimer())
</script>

<template>
  <img
    v-bind="$attrs"
    :key="imageKey"
    :src="src"
    :alt="alt"
    :class="{ 'is-loaded': loaded }"
    :aria-busy="retrying || (!loaded && !failed)"
    @load="handleLoad"
    @error="handleError"
  />
  <slot
    name="status"
    :loaded="loaded"
    :failed="failed"
    :retrying="retrying"
    :retry-count="retryCount"
    :max-retries="maxRetries"
    :retry="retryNow"
  />
</template>
