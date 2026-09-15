<script setup lang="ts">
import { Images } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchPublicGenerationStats } from '@/lib/api'
import type { PublicGenerationStats } from '@/lib/types'

const stats = ref<PublicGenerationStats | null>(null)
const activeIndex = ref(0)
const hovered = ref(false)
const focused = ref(false)
const numberFormat = new Intl.NumberFormat('zh-CN')
const messages = computed(() => stats.value ? [
  { label: '今日已生成图片', count: numberFormat.format(stats.value.today_images) },
  { label: '系统运行至今已生成', count: numberFormat.format(stats.value.total_images) },
] : [])
let rotationTimer: ReturnType<typeof setInterval> | undefined
let refreshTimer: ReturnType<typeof setInterval> | undefined
let requestController: AbortController | undefined

async function refreshStats() {
  if (document.hidden || requestController) return
  const controller = new AbortController()
  requestController = controller
  const timeout = setTimeout(() => controller.abort(), 10_000)
  try {
    const result = await fetchPublicGenerationStats(controller.signal)
    if (!controller.signal.aborted) stats.value = result
  } catch {
    // Hide unavailable statistics instead of presenting a failure as zero images.
    stats.value = null
    hovered.value = false
    focused.value = false
  } finally {
    clearTimeout(timeout)
    requestController = undefined
  }
}

function nextMessage() {
  activeIndex.value = (activeIndex.value + 1) % 2
}

onMounted(() => {
  void refreshStats()
  rotationTimer = setInterval(() => {
    if (!document.hidden && !hovered.value && !focused.value && stats.value) nextMessage()
  }, 5_000)
  refreshTimer = setInterval(() => { void refreshStats() }, 60_000)
  document.addEventListener('visibilitychange', refreshStats)
})

onBeforeUnmount(() => {
  clearInterval(rotationTimer)
  clearInterval(refreshTimer)
  requestController?.abort()
  document.removeEventListener('visibilitychange', refreshStats)
})
</script>

<template>
  <div class="generation-stats-slot">
    <button
      v-if="stats"
      type="button"
      class="generation-stats"
      :aria-label="`全局生成统计；${messages.map(message => `${message.label} ${message.count} 张`).join('；')}；点击切换`"
      title="点击切换统计；悬停或聚焦时暂停轮播。今日按北京时间统计"
      @click="nextMessage"
      @mouseenter="hovered = true"
      @mouseleave="hovered = false"
      @focus="focused = true"
      @blur="focused = false"
    >
      <Images :size="14" class="stats-icon" aria-hidden="true" />
      <span class="stats-viewport" aria-hidden="true">
        <Transition name="stats-roll">
          <span :key="activeIndex" class="stats-message">
            {{ messages[activeIndex]?.label }}
            <strong>{{ messages[activeIndex]?.count }}</strong> 张
          </span>
        </Transition>
      </span>
      <span class="stats-dots" aria-hidden="true">
        <span v-for="index in 2" :key="index" :class="{ active: activeIndex === index - 1 }" />
      </span>
    </button>
  </div>
</template>

<style scoped>
.generation-stats-slot {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: center;
  min-height: 36px;
  padding: 4px 16px 0;
}

.generation-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 24px;
}

.generation-stats:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

.stats-icon { flex-shrink: 0; color: var(--accent-strong); }
.stats-viewport { position: relative; width: 260px; height: 24px; overflow: hidden; }
.stats-message { position: absolute; inset: 0; white-space: nowrap; }
.stats-message strong { margin: 0 3px; color: var(--accent-strong); font-weight: 600; font-variant-numeric: tabular-nums; }
.stats-dots { display: flex; gap: 4px; flex-shrink: 0; }
.stats-dots span { width: 4px; height: 4px; border-radius: 50%; background: var(--border-accent); }
.stats-dots .active { background: var(--accent-strong); }

.stats-roll-enter-active, .stats-roll-leave-active {
  transition: transform 250ms cubic-bezier(0.4, 0, 0.2, 1), opacity 250ms cubic-bezier(0.4, 0, 0.2, 1);
}
.stats-roll-enter-from { transform: translateY(100%); opacity: 0; }
.stats-roll-leave-to { transform: translateY(-100%); opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .stats-roll-enter-active, .stats-roll-leave-active { transition: none; }
}
</style>
