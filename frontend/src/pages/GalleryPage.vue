<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useRouter } from 'vue-router'

import GalleryGrid from '@/components/GalleryGrid.vue'
import PromptModal from '@/components/PromptModal.vue'
import { deleteJob, fetchGallery, toggleJobFavorite, toggleJobPublic } from '@/lib/api'
import { isLoggedIn } from '@/lib/auth'
import type { GalleryItem } from '@/lib/types'

const router = useRouter()

const galleryItems = ref<GalleryItem[]>([])
const galleryTotal = ref(0)
const galleryPage = ref(1)
const galleryPageSize = ref(20)
const gallerySearch = ref('')
const galleryFromDate = ref('')
const galleryToDate = ref('')
const selectedItem = ref<GalleryItem | null>(null)
const feedback = ref('')
const loading = ref(true)

async function loadGallery(page = 1) {
  galleryPage.value = page
  const data = await fetchGallery({
    page,
    page_size: galleryPageSize.value,
    q: gallerySearch.value || undefined,
    from_date: galleryFromDate.value || undefined,
    to_date: galleryToDate.value || undefined,
  })
  galleryItems.value = data.items
  galleryTotal.value = data.total
}

function resetGalleryFilters() {
  gallerySearch.value = ''
  galleryFromDate.value = ''
  galleryToDate.value = ''
  void loadGallery(1)
}

async function handleDeleteItem(item: GalleryItem) {
  if (!confirm('确定要删除这幅作品吗？')) return
  try {
    await deleteJob(item.job_id)
    galleryItems.value = galleryItems.value.filter((g) => g.job_id !== item.job_id)
    galleryTotal.value = Math.max(0, galleryTotal.value - 1)
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '删除失败。'
  }
}

async function handleToggleFavorite(item: GalleryItem) {
  try {
    const result = await toggleJobFavorite(item.job_id)
    item.is_favorite = result.is_favorite
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '操作失败。'
  }
}

async function handleTogglePublic(item: GalleryItem) {
  if (!item.is_public && !confirm('确定将此作品公开到画廊吗？其他用户将可以看到它。')) return
  try {
    const result = await toggleJobPublic(item.job_id)
    item.is_public = result.is_public
  } catch (e) {
    feedback.value = e instanceof Error ? e.message : '操作失败。'
  }
}

onMounted(async () => {
  if (!isLoggedIn()) {
    router.push('/login')
    return
  }
  try {
    await loadGallery()
  } catch (error) {
    feedback.value = error instanceof Error ? error.message : '画廊加载失败，请刷新重试。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <p v-if="feedback" class="feedback-banner">{{ feedback }}</p>

  <div v-if="loading" class="loading-state">正在加载画廊...</div>
  <template v-else>
    <div class="gallery-header-row">
      <h2 class="gallery-heading">我的画廊</h2>
    </div>

    <div class="gallery-toolbar">
      <input
        v-model="gallerySearch"
        type="text"
        placeholder="搜索提示词..."
        class="gallery-search-input"
        @keyup.enter="loadGallery(1)"
      />
      <input v-model="galleryFromDate" type="date" class="gallery-date-input" @change="loadGallery(1)" />
      <span class="gallery-date-sep">至</span>
      <input v-model="galleryToDate" type="date" class="gallery-date-input" @change="loadGallery(1)" />
      <button class="ghost-button" @click="resetGalleryFilters">重置</button>
    </div>

    <GalleryGrid
      :items="galleryItems"
      :deletable="true"
      :show-owner-actions="true"
      @select="selectedItem = $event"
      @delete="handleDeleteItem"
      @toggle-favorite="handleToggleFavorite"
      @toggle-public="handleTogglePublic"
    />
    <div v-if="galleryTotal > galleryPageSize" class="gallery-pagination">
      <button class="ghost-button" :disabled="galleryPage <= 1" @click="loadGallery(galleryPage - 1)">上一页</button>
      <span class="gallery-page-info">{{ galleryPage }} / {{ Math.ceil(galleryTotal / galleryPageSize) }}</span>
      <button class="ghost-button" :disabled="galleryPage >= Math.ceil(galleryTotal / galleryPageSize)" @click="loadGallery(galleryPage + 1)">下一页</button>
    </div>

    <PromptModal
      :item="selectedItem"
      :is-owner="true"
      @close="selectedItem = null"
      @toggle-favorite="handleToggleFavorite"
      @toggle-public="handleTogglePublic"
    />
  </template>
</template>
