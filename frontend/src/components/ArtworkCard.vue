<script setup lang="ts">
import { computed, ref } from 'vue'
import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { useMediaClock } from '@/composables/useMediaClock'
import { mediaAvailable } from '@/lib/media-state'
import { resolveImageLayout } from '@/lib/image-layout'
import type { Artwork } from '@/lib/artworks'
const props = defineProps<{ item: Artwork; busy?: boolean }>()
const emit = defineEmits<{ select: []; favorite: []; invalid: [] }>()
const now = useMediaClock()
const available = computed(() => mediaAvailable(props.item.media_state, props.item.media_expires_at, now.value))
const ratio = ref('')
const statusLabel = computed(() => ({ queued: '排队中', processing: '生成中', succeeded: '生成成功', failed: '生成失败' }[props.item.status ?? ''] ?? '作品已失效'))
function loaded(event: Event) {
  const img = event.target as HTMLImageElement
  if (img.naturalWidth && img.naturalHeight) ratio.value = `${img.naturalWidth} / ${img.naturalHeight}`
}
</script>
<template>
  <article class="artwork-card">
    <button class="artwork-preview" :style="{ aspectRatio: ratio || resolveImageLayout(item.size, item.aspect_ratio).aspectRatio }" type="button" @click="emit('select')" :aria-label="available ? '查看作品详情' : '查看记录详情'">
      <ProtectedImage :src="item.thumbnail_url" :state="item.media_state" :expires-at="item.media_expires_at" :alt="item.title || item.prompt || '作品预览'" @loaded="loaded" @invalid="emit('invalid')" />
    </button>
    <div class="artwork-caption">
      <div class="artwork-badges"><span>{{ statusLabel }}</span><span v-if="item.is_in_gallery">已加入画廊{{ item.gallery_visible ? '' : ' · 未公开' }}</span><span v-if="item.submission_status === 'pending'">{{ available ? '待审核' : '投稿已过期' }}</span><span v-if="item.retention_kind === 'permanent'">社区收录</span></div>
      <p class="artwork-summary">{{ item.title || item.prompt || (available ? '作者未公开提示词' : '图片不可用，文字记录仍保留') }}</p>
      <MediaExpiry :state="item.media_state" :expires-at="item.media_expires_at" :permanent="item.retention_kind === 'permanent'" />
      <div class="artwork-actions">
        <button type="button" @click="emit('select')">{{ available ? '查看详情' : '查看记录' }}</button>
        <button type="button" :disabled="busy || (!available && !item.is_favorite)" :aria-pressed="item.is_favorite" @click="emit('favorite')">{{ item.is_favorite ? '取消收藏' : '收藏' }}</button>
      </div>
    </div>
  </article>
</template>
<style scoped>
.artwork-card {
  min-width: 0;
  margin-bottom: 24px;
  overflow: hidden;
  break-inside: avoid;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  transition: transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease;
}
.artwork-card:hover,
.artwork-card:focus-within {
  border-color: var(--border-accent);
  box-shadow: var(--shadow-md);
  transform: translateY(-4px);
}
.artwork-preview {
  display: block;
  width: 100%;
  padding: 0;
  overflow: hidden;
  border: 0;
  border-bottom: 1px solid var(--border-subtle);
  border-radius: 0;
  cursor: pointer;
  background: var(--bg-elevated);
}
.artwork-preview :deep(img) { transition: transform 300ms ease; }
.artwork-card:hover .artwork-preview :deep(img) { transform: scale(1.025); }
.artwork-preview:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.artwork-caption { padding: 13px 14px 10px; }
.artwork-badges { display: flex; gap: 5px; flex-wrap: wrap; font-size: 10px; color: var(--text-muted); }
.artwork-badges span {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 7px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
}
.artwork-summary {
  display: -webkit-box;
  overflow: hidden;
  margin: 10px 0 7px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.artwork-actions {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 10px -2px 0;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}
.artwork-actions button {
  min-height: 30px;
  padding: 4px 7px;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  transition: color 160ms ease, background 160ms ease;
}
.artwork-actions button[aria-pressed='true'],
.artwork-actions button:hover { color: var(--accent-strong); background: var(--accent-glow); }
.artwork-actions button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.artwork-actions button:disabled { color: var(--text-muted); background: transparent; cursor: default; opacity: .55; }
@media (prefers-reduced-motion: reduce) {
  .artwork-card,
  .artwork-preview :deep(img) { transition: none; }
}
</style>
