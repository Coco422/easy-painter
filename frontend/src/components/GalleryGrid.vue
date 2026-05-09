<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Heart, Star, Globe, Lock } from 'lucide-vue-next'

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

function updateColumnCount() {
  const w = window.innerWidth
  columnCount.value = w >= 1200 ? 4 : w >= 768 ? 3 : 2
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
          @click="emit('select', item)"
        >
          <img :src="item.image_url" :alt="item.prompt" loading="lazy" />
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
