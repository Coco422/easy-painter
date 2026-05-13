<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { InspirationItem } from '@/lib/types'

const props = defineProps<{
  items: InspirationItem[]
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [item: InspirationItem]
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

const columns = computed(() => {
  const cols: InspirationItem[][] = Array.from({ length: columnCount.value }, () => [])
  props.items.forEach((item, i) => cols[i % columnCount.value].push(item))
  return cols
})
</script>

<template>
  <section class="inspiration-section">
    <div class="inspiration-grid">
      <div v-for="(col, colIdx) in columns" :key="colIdx" class="inspiration-column">
        <div v-for="item in col" :key="item.id" class="inspiration-card-wrap">
          <button
            class="inspiration-card"
            type="button"
            @click="emit('select', item)"
          >
            <img :src="item.image_url" :alt="item.title" loading="lazy" />
            <div class="inspiration-card-overlay">
              <span v-if="item.source === 'gallery'" class="inspiration-source-tag source-gallery">社区</span>
              <span v-else class="inspiration-source-tag source-external">灵感库</span>
              <div class="inspiration-card-info">
                <p class="inspiration-card-title">{{ item.title }}</p>
                <div class="inspiration-card-meta">
                  <span v-if="item.author_name" class="inspiration-card-author">{{ item.author_name }}</span>
                  <span v-if="item.like_count > 0" class="inspiration-card-likes">{{ item.like_count }}</span>
                </div>
              </div>
            </div>
          </button>
        </div>
      </div>
    </div>
    <div v-if="loading" class="inspiration-loading">加载中...</div>
    <div v-if="!loading && items.length === 0" class="inspiration-empty">暂无灵感内容</div>
  </section>
</template>

<style scoped>
.inspiration-section {
  width: 100%;
}

.inspiration-grid {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.inspiration-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.inspiration-card-wrap {
  position: relative;
}

.inspiration-card {
  display: block;
  width: 100%;
  border: none;
  padding: 0;
  background: none;
  cursor: pointer;
  border-radius: var(--radius-md, 10px);
  overflow: hidden;
  position: relative;
  transition: transform 200ms ease, box-shadow 200ms ease;
}

.inspiration-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.inspiration-card img {
  width: 100%;
  display: block;
  object-fit: cover;
}

.inspiration-card-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.6) 0%, transparent 60%);
  opacity: 0;
  transition: opacity 200ms ease;
  padding: 12px;
}

.inspiration-card:hover .inspiration-card-overlay {
  opacity: 1;
}

.inspiration-source-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
}

.source-gallery {
  background: rgba(59, 130, 246, 0.85);
}

.source-external {
  background: rgba(168, 85, 247, 0.85);
}

.inspiration-card-info {
  color: #fff;
}

.inspiration-card-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.inspiration-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
  opacity: 0.8;
}

.inspiration-loading,
.inspiration-empty {
  text-align: center;
  padding: 32px 0;
  color: var(--text-secondary);
  font-size: 14px;
}
</style>
