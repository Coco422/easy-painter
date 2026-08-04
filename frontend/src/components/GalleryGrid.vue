<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Heart, Star, Globe, Lock } from 'lucide-vue-next'

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
const loadedImageIds = ref(new Set<string>())
const failedImageIds = ref(new Set<string>())
const actualImageAspectRatios = ref(new Map<string, string>())

function updateColumnCount() {
  const w = window.innerWidth
  columnCount.value = w >= 1200 ? 4 : w >= 768 ? 3 : 2
}

function displayedAspectRatio(item: GalleryItem) {
  return actualImageAspectRatios.value.get(item.job_id) ?? resolveImageLayout(item.size, item.aspect_ratio).aspectRatio
}

function markImageLoaded(jobId: string, event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.naturalWidth > 0 && image.naturalHeight > 0) {
    const ratios = new Map(actualImageAspectRatios.value)
    ratios.set(jobId, `${image.naturalWidth} / ${image.naturalHeight}`)
    actualImageAspectRatios.value = ratios
  }
  loadedImageIds.value = new Set(loadedImageIds.value).add(jobId)
  const failed = new Set(failedImageIds.value)
  failed.delete(jobId)
  failedImageIds.value = failed
}

function markImageFailed(jobId: string) {
  failedImageIds.value = new Set(failedImageIds.value).add(jobId)
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
          @click="emit('select', item)"
        >
          <span
            v-if="!loadedImageIds.has(item.job_id)"
            class="gallery-card-skeleton"
            :class="{ 'is-error': failedImageIds.has(item.job_id) }"
            aria-hidden="true"
          >
            <small>{{ failedImageIds.has(item.job_id) ? '载入失败' : '' }}</small>
          </span>
          <img
            :src="item.image_url"
            :alt="item.prompt"
            :width="resolveImageLayout(item.size, item.aspect_ratio).width"
            :height="resolveImageLayout(item.size, item.aspect_ratio).height"
            :class="{ 'is-loaded': loadedImageIds.has(item.job_id) }"
            loading="lazy"
            @load="markImageLoaded(item.job_id, $event)"
            @error="markImageFailed(item.job_id)"
          />
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
