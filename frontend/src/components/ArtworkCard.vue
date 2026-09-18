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
.artwork-card { min-width: 0; break-inside: avoid; margin-bottom: 24px; }
.artwork-preview { display: block; width: 100%; padding: 0; border: 0; border-radius: var(--radius-md); overflow: hidden; cursor: pointer; background: var(--bg-elevated); }
.artwork-preview:hover { outline: 1px solid var(--border-accent); }
.artwork-caption { padding: 12px 2px 0; }
.artwork-badges { display: flex; gap: 8px; flex-wrap: wrap; font-size: 11px; color: var(--text-muted); }
.artwork-summary { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin: 8px 0; line-height: 1.6; font-size: 14px; }
.artwork-actions { display: flex; justify-content: space-between; margin-top: 10px; }
.artwork-actions button { color: var(--text-secondary); border: 0; background: none; padding: 6px 0; cursor: pointer; font: inherit; font-size: 13px; }
.artwork-actions button[aria-pressed='true'], .artwork-actions button:hover { color: var(--accent); }
.artwork-actions button:disabled { color: var(--text-muted); cursor: default; }
</style>
