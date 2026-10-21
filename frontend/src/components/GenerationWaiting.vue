<script setup lang="ts">
import { Sparkles } from 'lucide-vue-next'
import type { GenerationQuip } from '@/lib/generation-quips'

defineProps<{
  status: 'queued' | 'processing'
  quip: GenerationQuip
  compact?: boolean
  hint?: string | null
}>()
</script>

<template>
  <div class="generation-waiting" :class="{ 'generation-waiting--compact': compact }">
    <span class="waiting-mark" aria-hidden="true"><Sparkles :size="compact ? 20 : 28" /></span>
    <span class="waiting-status" role="status">{{ status === 'queued' ? '排队中' : '生成中' }}<span class="waiting-dots" aria-hidden="true"><i /><i /><i /></span></span>
    <span class="waiting-quip-slot" aria-live="off"><span :key="quip.sequence" class="waiting-quip">{{ quip.text }}</span></span>
    <template v-if="!compact"><span v-if="hint" class="waiting-hint">{{ hint }}</span><span class="waiting-note">结果会自动显示在这里，无需重复提交。</span></template>
  </div>
</template>

<style scoped>
.generation-waiting { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; width: 100%; height: 100%; padding: 24px; text-align: center; background: var(--bg-input); }
.waiting-mark { display: inline-flex; align-items: center; justify-content: center; width: 48px; height: 48px; color: var(--accent); animation: waiting-breathe 3.2s ease-in-out infinite; }
.waiting-status { display: inline-flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 12px; }
.waiting-dots { display: inline-flex; gap: 3px; }
.waiting-dots i { width: 3px; height: 3px; border-radius: 50%; background: var(--accent); animation: waiting-dot 1.5s ease-in-out infinite; }
.waiting-dots i:nth-child(2) { animation-delay: 180ms; }
.waiting-dots i:nth-child(3) { animation-delay: 360ms; }
.waiting-quip-slot { display: grid; align-items: center; width: 100%; max-width: 440px; min-height: 3.2em; margin: 4px 0 8px; color: var(--text-primary); font-size: clamp(16px, 1.6vw, 20px); line-height: 1.6; }
.waiting-quip { display: block; overflow-wrap: anywhere; text-wrap: balance; animation: waiting-reveal 250ms cubic-bezier(0.4, 0, 0.2, 1) both; }
.waiting-hint, .waiting-note { max-width: 440px; color: var(--text-muted); font-size: 12px; line-height: 1.7; }
.waiting-hint { color: var(--text-secondary); }
.generation-waiting--compact { gap: 6px; padding: 12px; }
.generation-waiting--compact .waiting-mark { width: 28px; height: 28px; }
.generation-waiting--compact .waiting-status { font-size: 11px; }
.generation-waiting--compact .waiting-quip-slot { max-width: 240px; margin: 2px 0 0; font-size: 13px; }
@media (max-width: 450px) {
  .generation-waiting { padding: 16px; gap: 8px; }
  .waiting-mark { width: 36px; height: 36px; }
  .generation-waiting--compact { padding: 8px; gap: 4px; }
  .generation-waiting--compact .waiting-mark { display: none; }
  .generation-waiting--compact .waiting-quip-slot { font-size: 12px; }
}
@keyframes waiting-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
@keyframes waiting-breathe { 0%, 100% { opacity: .65; transform: rotate(-6deg) scale(.95); } 50% { opacity: 1; transform: rotate(6deg) scale(1.05); } }
@keyframes waiting-dot { 0%, 80%, 100% { opacity: .3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }
@media (prefers-reduced-motion: reduce) { .waiting-mark, .waiting-quip, .waiting-dots i { animation: none; } }
</style>
