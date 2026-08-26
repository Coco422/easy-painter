<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { LockKeyhole } from 'lucide-vue-next'

import InspirationDetailModal from '@/components/InspirationDetailModal.vue'
import InspirationGrid from '@/components/InspirationGrid.vue'
import { fetchInspirationCategories, fetchInspirations } from '@/lib/api'
import { authState } from '@/lib/auth'
import type { InspirationItem } from '@/lib/types'

const GUEST_PREVIEW_LIMIT = 20
const items = ref<InspirationItem[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const loading = ref(true)
const loadingMore = ref(false)
const hasMore = ref(true)
const searchQuery = ref('')
const selectedSource = ref('')
const selectedCategory = ref('')
const sortMode = ref<'recent' | 'featured'>('recent')
const selectedItem = ref<InspirationItem | null>(null)
const scrollSentinel = ref<HTMLElement | null>(null)
const communityTags = ref<string[]>([])
let scrollObserver: IntersectionObserver | null = null
const isGuest = computed(() => !authState.token)
const guestRemainingCount = computed(() => Math.max(0, total.value - items.value.length))
const showGuestGate = computed(() => (
  isGuest.value
  && !loading.value
  && items.value.length >= GUEST_PREVIEW_LIMIT
  && guestRemainingCount.value > 0
))

async function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  if (isGuest.value && offset.value >= GUEST_PREVIEW_LIMIT) {
    hasMore.value = false
    return
  }
  loadingMore.value = true
  try {
    const requestLimit = isGuest.value
      ? Math.min(limit.value, GUEST_PREVIEW_LIMIT - offset.value)
      : limit.value
    const data = await fetchInspirations({
      offset: offset.value,
      limit: requestLimit,
      q: searchQuery.value || undefined,
      source: selectedSource.value || undefined,
      category: selectedCategory.value || undefined,
      sort: sortMode.value,
    })
    items.value.push(...data.items)
    offset.value += data.items.length
    total.value = data.total
    const reachedGuestLimit = isGuest.value && offset.value >= GUEST_PREVIEW_LIMIT
    hasMore.value = !reachedGuestLimit && data.items.length >= requestLimit && offset.value < data.total
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
  selectedCategory.value = ''
  resetFeed()
}

function handleCategoryChange(category: string) {
  selectedCategory.value = selectedCategory.value === category ? '' : category
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
  fetchInspirationCategories().then(tags => { communityTags.value = tags }).catch(() => {})
})
</script>

<template>
  <section class="inspiration-page">
    <div class="inspiration-header">
      <h1 class="inspiration-title">社区灵感</h1>
      <p class="inspiration-subtitle">探索管理员导入或精选收录的永久创作提示词，一键复用</p>
      <div class="source-explainer" aria-label="内容来源说明">
        <div>
          <strong>管理员精选</strong>
          <span>从公开作品中审核收录，独立保存，不受原作清理影响。</span>
        </div>
        <div>
          <strong>导入灵感</strong>
          <span>由管理员导入并保存至本站的提示词和创作示例。</span>
        </div>
      </div>
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
            :class="{ active: selectedSource === 'community-curated' }"
            @click="handleSourceChange('community-curated')"
          >精选</button>
          <button
            class="source-pill"
            :class="{ active: selectedSource === 'imported' }"
            @click="handleSourceChange('imported')"
          >导入</button>
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

    <div v-if="communityTags.length > 0" class="category-filter">
      <button
        v-for="tag in communityTags.slice(0, 12)"
        :key="tag"
        class="category-pill"
        :class="{ active: selectedCategory === tag }"
        @click="handleCategoryChange(tag)"
      >{{ tag }}</button>
    </div>

    <div v-if="items.length > 0 || loading" class="inspiration-feed">
      <InspirationGrid
        :items="items"
        :loading="loading"
        @select="selectedItem = $event"
      />

      <aside v-if="showGuestGate" class="guest-preview-gate" aria-labelledby="guest-preview-title">
        <div class="guest-preview-lock" aria-hidden="true">
          <LockKeyhole :size="20" :stroke-width="1.7" />
        </div>
        <p class="guest-preview-kicker">访客预览已结束</p>
        <h2 id="guest-preview-title">登录后，继续逛灵感库</h2>
        <p>
          已为你展示 {{ GUEST_PREVIEW_LIMIT }} 个案例。登录后可继续浏览其余
          {{ guestRemainingCount }} 个案例，探索更多创作思路。
        </p>
        <router-link to="/login" class="guest-preview-action">登录继续浏览</router-link>
        <small>登录后解除访客浏览上限</small>
      </aside>
    </div>

    <div v-if="!loading && items.length === 0" class="inspiration-empty-state">
      <p class="empty-title">灵感库正在建设中</p>
      <p class="empty-subtitle">敬请期待更多精彩内容</p>
      <router-link to="/create" class="empty-link">直接去创作 →</router-link>
    </div>

    <div v-if="!showGuestGate" ref="scrollSentinel" class="scroll-sentinel">
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

.source-explainer {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: min(680px, 100%);
  margin: 20px auto 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  text-align: left;
}

.source-explainer > div {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
}

.source-explainer > div + div {
  border-left: 1px solid var(--border);
}

.source-explainer strong {
  color: var(--text-primary);
  font-size: 13px;
}

.source-explainer span {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
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

.category-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 20px;
}

.category-pill {
  padding: 4px 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.category-pill:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.category-pill.active {
  background: var(--accent);
  border-color: var(--accent);
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

.guest-preview-gate {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  margin: -112px auto 40px;
  padding: 156px 32px 36px;
  color: var(--text-primary);
  text-align: center;
  background: linear-gradient(
    to bottom,
    transparent 0,
    color-mix(in srgb, var(--bg-deep) 88%, transparent) 92px,
    var(--bg-deep) 132px
  );
}

.guest-preview-lock {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 16px;
  border: 1px solid var(--border-accent);
  border-radius: 50%;
  color: var(--accent);
  background: var(--bg-surface);
}

.guest-preview-kicker {
  margin: 0 0 8px;
  color: var(--accent);
  font: 700 11px/1.4 var(--font-mono);
  letter-spacing: 0.12em;
}

.guest-preview-gate h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(24px, 4vw, 32px);
  font-weight: 600;
}

.guest-preview-gate > p:not(.guest-preview-kicker) {
  max-width: 520px;
  margin: 12px 0 24px;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.8;
}

.guest-preview-action {
  min-width: 180px;
  padding: 11px 24px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  color: var(--text-inverse);
  background: var(--accent);
  font-size: 14px;
  font-weight: 700;
  transition: background-color 200ms ease, border-color 200ms ease, transform 200ms ease;
}

.guest-preview-action:hover {
  border-color: var(--accent-strong);
  background: var(--accent-strong);
  transform: translateY(-1px);
}

.guest-preview-action:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}

.guest-preview-gate small {
  margin-top: 12px;
  color: var(--text-muted);
  font-size: 11px;
}

@media (max-width: 620px) {
  .source-explainer { grid-template-columns: 1fr; }
  .source-explainer > div + div { border-top: 1px solid var(--border); border-left: 0; }
  .guest-preview-gate { padding-inline: 20px; }
}
</style>
