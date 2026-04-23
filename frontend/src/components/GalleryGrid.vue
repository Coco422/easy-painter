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
      <div>
        <p class="section-label">最近完成的画图任务</p>
        <h2>灵感画廊</h2>
      </div>
      <p class="section-caption">点击作品卡片查看完整提示词与修订提示词</p>
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
        <div class="gallery-overlay">
          <p>{{ item.prompt }}</p>
          <span>{{ item.model }}</span>
        </div>
      </button>
    </div>
  </section>
</template>
