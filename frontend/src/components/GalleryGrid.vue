<script setup lang="ts">
import type { GalleryItem } from '@/lib/types'

defineProps<{
  items: GalleryItem[]
  showUsername?: boolean
  deletable?: boolean
}>()

const emit = defineEmits<{
  select: [item: GalleryItem]
  delete: [item: GalleryItem]
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
