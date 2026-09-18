<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { BadgeCheck, Heart, Layers3 } from 'lucide-vue-next'

import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
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
            <span class="inspiration-card-media">
              <ProtectedImage :src="item.thumbnail_url" :alt="item.title" />
              <span v-if="item.source === 'community-curated'" class="inspiration-source-tag source-gallery">
                <BadgeCheck :size="13" :stroke-width="1.9" aria-hidden="true" />
                社区精选
              </span>
              <span v-else class="inspiration-source-tag source-external">
                <Layers3 :size="13" :stroke-width="1.9" aria-hidden="true" />
                灵感收录
              </span>
            </span>
            <span class="inspiration-card-info">
              <span v-if="item.categories && item.categories.length > 0" class="inspiration-card-tags">
                <span v-for="cat in item.categories.slice(0, 3)" :key="cat" class="inspiration-card-tag">{{ cat }}</span>
              </span>
              <span class="inspiration-card-title">{{ item.title }}</span>
              <span class="inspiration-card-meta">
                <span v-if="item.author_name" class="inspiration-card-author">{{ item.author_name }}</span>
                <span v-if="item.like_count > 0" class="inspiration-card-likes" :aria-label="`${item.like_count} 次喜欢`">
                  <Heart :size="12" :stroke-width="1.8" aria-hidden="true" />
                  {{ item.like_count }}
                </span>
                <MediaExpiry state="available" permanent />
              </span>
            </span>
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
  gap: 24px;
  align-items: flex-start;
}

.inspiration-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0;
}

.inspiration-card-wrap {
  position: relative;
}

.inspiration-card {
  display: block;
  width: 100%;
  border: 1px solid var(--border);
  padding: 0;
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
  border-radius: var(--radius-md, 10px);
  overflow: hidden;
  position: relative;
  text-align: left;
  box-shadow: var(--shadow-sm);
  transition: transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease;
}

.inspiration-card:hover,
.inspiration-card:focus-visible {
  transform: translateY(-4px);
  border-color: var(--border-accent);
  box-shadow: var(--shadow-md);
}

.inspiration-card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}

.inspiration-card-media {
  position: relative;
  display: block;
  overflow: hidden;
  background: var(--bg-elevated);
}

.inspiration-card :deep(img) {
  width: 100%;
  display: block;
  object-fit: cover;
  transition: transform 300ms ease;
}

.inspiration-card:hover :deep(img),
.inspiration-card:focus-visible :deep(img) {
  transform: scale(1.025);
}

.inspiration-source-tag {
  position: absolute;
  top: 10px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 26px;
  padding: 4px 8px 4px 7px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 650;
  line-height: 1;
  letter-spacing: 0.02em;
  color: rgba(255, 255, 255, 0.92);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);
  backdrop-filter: blur(10px) saturate(0.8);
}

.source-gallery {
  border-color: rgba(205, 220, 180, 0.32);
  background: rgba(35, 43, 35, 0.86);
  color: #eef4e6;
}

.source-external {
  background: rgba(35, 36, 34, 0.8);
  color: rgba(255, 255, 255, 0.82);
}

.inspiration-card-info {
  display: grid;
  gap: 10px;
  padding: 13px 14px 14px;
  border-top: 1px solid var(--border-subtle);
}

.inspiration-card-title {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.55;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.inspiration-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.inspiration-card-tag {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 7px;
  border: 1px solid var(--border-accent);
  border-radius: var(--radius-sm);
  background: var(--accent-glow);
  font-size: 10px;
  font-weight: 600;
  color: var(--accent-strong);
}

.inspiration-card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.inspiration-card-author {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspiration-card-likes {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.inspiration-card-meta :deep(.media-expiry) {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 11px;
}

.inspiration-loading,
.inspiration-empty {
  text-align: center;
  padding: 32px 0;
  color: var(--text-secondary);
  font-size: 14px;
}

@media (max-width: 767px) {
  .inspiration-grid,
  .inspiration-column { gap: 16px; }
  .inspiration-card-info { padding: 11px 12px 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .inspiration-card,
  .inspiration-card :deep(img) { transition: none; }
}
</style>
