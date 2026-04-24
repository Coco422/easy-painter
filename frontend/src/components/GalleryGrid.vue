<script setup lang="ts">
import type { GalleryItem } from '@/lib/types'

defineProps<{
  items: GalleryItem[]
}>()

const emit = defineEmits<{
  select: [item: GalleryItem]
}>()
</script>

<template>
  <section class="gallery-section" id="gallery">
    <div class="section-heading">
      <h2>最近作品</h2>
    </div>

    <div class="gallery-grid">
      <button
        v-for="item in items"
        :key="item.job_id"
        class="gallery-card"
        type="button"
        @click="emit('select', item)"
      >
        <img :src="item.image_url" :alt="item.prompt" loading="lazy" />
      </button>
    </div>
  </section>
</template>
