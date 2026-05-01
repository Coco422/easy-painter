<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import GalleryGrid from '@/components/GalleryGrid.vue'
import PromptModal from '@/components/PromptModal.vue'
import { fetchPublicGallery } from '@/lib/api'
import type { GalleryItem } from '@/lib/types'

const route = useRoute()
const gallery = ref<GalleryItem[]>([])
const loading = ref(true)
const error = ref('')
const selectedItem = ref<GalleryItem | null>(null)
const displayName = ref('')

async function loadGallery() {
  const username = route.params.username as string
  loading.value = true
  error.value = ''
  try {
    gallery.value = await fetchPublicGallery(username)
    if (gallery.value.length > 0 && gallery.value[0].username) {
      displayName.value = gallery.value[0].username
    } else {
      displayName.value = username
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '该用户不存在或未公开画廊。'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadGallery()
})
</script>

<template>
  <div class="public-gallery-page">
    <div v-if="loading" class="loading-state">正在加载画廊…</div>
    <div v-else-if="error" class="gallery-error">
      <p>{{ error }}</p>
      <router-link to="/" class="back-link">返回首页</router-link>
    </div>
    <template v-else>
      <h2 class="gallery-heading">{{ displayName }} 的画廊</h2>
      <GalleryGrid :items="gallery" @select="selectedItem = $event" />
    </template>

    <PromptModal :item="selectedItem" @close="selectedItem = null" />
  </div>
</template>
