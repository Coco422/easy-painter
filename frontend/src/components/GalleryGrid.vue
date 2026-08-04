<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Heart, Star, Globe, Lock } from 'lucide-vue-next'

import RetryableImage from '@/components/RetryableImage.vue'
import { resolveImageLayout } from '@/lib/image-layout'
import type { GalleryItem } from '@/lib/types'

const props = defineProps<{
  items: GalleryItem[]
  showUsername?: boolean
  deletable?: boolean
  showOwnerActions?: boolean
  showLikes?: boolean
}>()

const emit = defineEmits<{
  select: [item: GalleryItem]
  delete: [item: GalleryItem]
  toggleFavorite: [item: GalleryItem]
  togglePublic: [item: GalleryItem]
  toggleLike: [item: GalleryItem]
}>()

const columnCount = ref(4)
const failedImageIds = ref(new Set<string>())
const actualImageAspectRatios = ref(new Map<string, string>())
const imageRetryKeys = ref(new Map<string, number>())
const GALLERY_IMAGE_RETRY_DELAYS_MS = [2000, 8000]

function updateColumnCount() {
  const w = window.innerWidth
  columnCount.value = w >= 1200 ? 4 : w >= 768 ? 3 : 2
}

function displayedAspectRatio(item: GalleryItem) {
  return actualImageAspectRatios.value.get(item.job_id) ?? resolveImageLayout(item.size, item.aspect_ratio).aspectRatio
}

function imageRetryKey(jobId: string) {
  return imageRetryKeys.value.get(jobId) ?? 0
}

function markImageLoaded(jobId: string, event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.naturalWidth > 0 && image.naturalHeight > 0) {
    const ratios = new Map(actualImageAspectRatios.value)
    ratios.set(jobId, `${image.naturalWidth} / ${image.naturalHeight}`)
    actualImageAspectRatios.value = ratios
  }
  const failed = new Set(failedImageIds.value)
  failed.delete(jobId)
  failedImageIds.value = failed
}

function markImageFailed(jobId: string) {
  failedImageIds.value = new Set(failedImageIds.value).add(jobId)
}

function handleCardClick(item: GalleryItem) {
  if (!failedImageIds.value.has(item.job_id)) {
    emit('select', item)
    return
  }

  const retryKeys = new Map(imageRetryKeys.value)
  retryKeys.set(item.job_id, (retryKeys.get(item.job_id) ?? 0) + 1)
  imageRetryKeys.value = retryKeys

  const failed = new Set(failedImageIds.value)
  failed.delete(item.job_id)
  failedImageIds.value = failed
}

onMounted(() => {
  updateColumnCount()
  window.addEventListener('resize', updateColumnCount)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateColumnCount)
})

// Stable column distribution — items assigned by index never move on append
const columns = computed(() => {
  const cols: GalleryItem[][] = Array.from({ length: columnCount.value }, () => [])
  props.items.forEach((item, i) => cols[i % columnCount.value].push(item))
  return cols
})
</script>

<template>
  <section class="gallery-section" id="gallery">
    <div class="gallery-grid">
      <div v-for="(col, colIdx) in columns" :key="colIdx" class="gallery-column">
        <div
          v-for="item in col"
          :key="item.job_id"
          class="gallery-card-wrap"
        >
        <button
          class="gallery-card"
          type="button"
          :style="{ aspectRatio: displayedAspectRatio(item) }"
          @click="handleCardClick(item)"
        >
          <RetryableImage
            :src="item.image_url"
            :alt="item.prompt"
            :retry-delays="GALLERY_IMAGE_RETRY_DELAYS_MS"
            :reset-key="imageRetryKey(item.job_id)"
            :width="resolveImageLayout(item.size, item.aspect_ratio).width"
            :height="resolveImageLayout(item.size, item.aspect_ratio).height"
            loading="lazy"
            @load="markImageLoaded(item.job_id, $event)"
            @failed="markImageFailed(item.job_id)"
          >
            <template #status="{ loaded, failed, retrying }">
              <span
                v-if="!loaded"
                class="gallery-card-skeleton"
                :class="{ 'is-error': failed }"
                role="status"
                aria-live="polite"
              >
                <small v-if="failed">载入失败，点击重试</small>
                <small v-else-if="retrying">连接不稳定，正在重试</small>
              </span>
            </template>
          </RetryableImage>
          <span v-if="showUsername && item.username" class="gallery-card-username">{{ item.username }}</span>
        </button>
        <div v-if="showOwnerActions" class="gallery-card-owner-actions">
          <button
            class="gallery-action-btn"
            :class="{ active: item.is_favorite }"
            type="button"
            title="收藏"
            @click.stop="emit('toggleFavorite', item)"
          >
            <Star :size="16" :fill="item.is_favorite ? 'currentColor' : 'none'" />
          </button>
          <button
            class="gallery-action-btn"
            :class="{ active: item.is_public }"
            type="button"
            :title="item.is_public ? '公开' : '私密'"
            @click.stop="emit('togglePublic', item)"
          >
            <Globe v-if="item.is_public" :size="16" />
            <Lock v-else :size="16" />
          </button>
        </div>
        <div v-if="showLikes" class="gallery-card-like-bar">
          <button
            class="gallery-like-btn"
            :class="{ liked: item.liked_by_me }"
            type="button"
            @click.stop="emit('toggleLike', item)"
          >
            <Heart :size="14" :fill="item.liked_by_me ? 'currentColor' : 'none'" />
            <span v-if="(item.like_count ?? 0) > 0">{{ item.like_count }}</span>
          </button>
        </div>
        <button
          v-if="deletable"
          class="gallery-card-delete"
          type="button"
          title="删除"
          @click.stop="emit('delete', item)"
        >×</button>
      </div>
      </div>
    </div>
  </section>
</template>
