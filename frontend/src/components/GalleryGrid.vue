<script setup lang="ts">
import { Heart, Star, Globe, Lock } from 'lucide-vue-next'

import type { GalleryItem } from '@/lib/types'

defineProps<{
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
</script>

<template>
  <section class="gallery-section" id="gallery">
    <div class="gallery-grid">
      <div
        v-for="item in items"
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
  </section>
</template>
