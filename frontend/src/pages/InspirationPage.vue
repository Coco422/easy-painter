<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import InspirationDetailModal from '@/components/InspirationDetailModal.vue'
import InspirationGrid from '@/components/InspirationGrid.vue'
import { fetchInspirations } from '@/lib/api'
import type { InspirationItem } from '@/lib/types'

const items = ref<InspirationItem[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const loading = ref(true)
const loadingMore = ref(false)
const hasMore = ref(true)
const searchQuery = ref('')
const selectedSource = ref('')
const sortMode = ref<'recent' | 'featured'>('recent')
const selectedItem = ref<InspirationItem | null>(null)
const scrollSentinel = ref<HTMLElement | null>(null)
let scrollObserver: IntersectionObserver | null = null

async function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const data = await fetchInspirations({
      offset: offset.value,
      limit: limit.value,
      q: searchQuery.value || undefined,
      source: selectedSource.value || undefined,
      sort: sortMode.value,
    })
    items.value.push(...data.items)
    offset.value += data.items.length
    hasMore.value = data.items.length >= limit.value
    total.value = data.total
  } catch (error) {
    console.error('Failed to load inspirations:', error)
  } finally {
    loadingMore.value = false
    loading.value = false
  }
}

function resetFeed() {
  items.value = []
  offset.value = 0
  hasMore.value = true
  loading.value = true
  void loadMore()
}

function handleSearch() {
  resetFeed()
}

function handleSourceChange(source: string) {
  selectedSource.value = source
  resetFeed()
}

function handleSortChange(sort: 'recent' | 'featured') {
  sortMode.value = sort
  resetFeed()
}

function observeSentinel() {
  nextTick(() => {
    if (scrollSentinel.value && scrollObserver) {
      scrollObserver.observe(scrollSentinel.value)
    }
  })
}

onBeforeUnmount(() => {
  if (scrollObserver) {
    scrollObserver.disconnect()
    scrollObserver = null
  }
})

onMounted(() => {
  scrollObserver = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && !loadingMore.value && hasMore.value) {
        void loadMore()
      }
    },
    { rootMargin: '200px' },
  )
  void loadMore()
  observeSentinel()
})
</script>

<template>
  <section class="inspiration-page">
    <div class="inspiration-header">
      <h1 class="inspiration-title">社区灵感</h1>
      <p class="inspiration-subtitle">探索来自社区和灵感库的创作提示词，一键复用</p>
    </div>

    <div class="inspiration-toolbar">
      <div class="toolbar-left">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索灵感..."
          class="inspiration-search-input"
          @keyup.enter="handleSearch"
        />
      </div>
      <div class="toolbar-right">
        <div class="source-pills">
          <button
            class="source-pill"
            :class="{ active: selectedSource === '' }"
            @click="handleSourceChange('')"
          >全部</button>
          <button
            class="source-pill"
            :class="{ active: selectedSource === 'gallery' }"
            @click="handleSourceChange('gallery')"
          >社区</button>
          <button
            class="source-pill"
            :class="{ active: selectedSource !== '' && selectedSource !== 'gallery' }"
            @click="handleSourceChange('awesome-gpt-image-2')"
          >灵感库</button>
        </div>
        <div class="sort-toggle">
          <button
            class="sort-btn"
            :class="{ active: sortMode === 'recent' }"
            @click="handleSortChange('recent')"
          >最近</button>
          <button
            class="sort-btn"
            :class="{ active: sortMode === 'featured' }"
            @click="handleSortChange('featured')"
          >精选</button>
        </div>
      </div>
    </div>

    <InspirationGrid
      v-if="items.length > 0 || loading"
      :items="items"
      :loading="loading"
      @select="selectedItem = $event"
    />

    <div v-if="!loading && items.length === 0" class="inspiration-empty-state">
      <p class="empty-title">灵感库正在建设中</p>
      <p class="empty-subtitle">敬请期待更多精彩内容</p>
      <router-link to="/create" class="empty-link">直接去创作 →</router-link>
    </div>

    <div ref="scrollSentinel" class="scroll-sentinel">
      <span v-if="loadingMore">加载中...</span>
      <span v-else-if="!hasMore && items.length > 0">没有更多了</span>
    </div>
  </section>

  <InspirationDetailModal
    :item="selectedItem"
    @close="selectedItem = null"
  />
</template>

<style scoped>
.inspiration-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 16px;
}

.inspiration-header {
  text-align: center;
  padding: 32px 0 24px;
}

.inspiration-title {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
}

.inspiration-subtitle {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--text-secondary);
}

.inspiration-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.toolbar-left {
  flex: 1;
  min-width: 200px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.inspiration-search-input {
  width: 100%;
  max-width: 320px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  background: var(--bg-card);
  color: var(--text);
  font-size: 14px;
  outline: none;
  transition: border-color 200ms;
}

.inspiration-search-input:focus {
  border-color: var(--accent);
}

.source-pills {
  display: flex;
  gap: 4px;
}

.source-pill {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.source-pill:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.source-pill.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-foreground, #fff);
}

.sort-toggle {
  display: flex;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  overflow: hidden;
}

.sort-btn {
  padding: 4px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.sort-btn:hover {
  color: var(--text);
}

.sort-btn.active {
  background: var(--accent);
  color: var(--accent-foreground, #fff);
}

.inspiration-empty-state {
  text-align: center;
  padding: 64px 0;
}

.empty-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.empty-subtitle {
  margin: 8px 0 24px;
  font-size: 14px;
  color: var(--text-secondary);
}

.empty-link {
  display: inline-block;
  padding: 10px 24px;
  background: var(--accent);
  color: var(--accent-foreground, #fff);
  border-radius: var(--radius-sm, 6px);
  text-decoration: none;
  font-weight: 500;
  transition: opacity 200ms;
}

.empty-link:hover {
  opacity: 0.9;
}

.scroll-sentinel {
  text-align: center;
  padding: 24px 0;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
