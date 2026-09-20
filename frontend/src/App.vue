<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AnnouncementBanner from '@/components/AnnouncementBanner.vue'
import GenerationStatsTicker from '@/components/GenerationStatsTicker.vue'
import { fetchPublicMeta } from '@/lib/api'
import { fetchCurrentUser, isLoggedIn } from '@/lib/auth'
import { initTheme } from '@/lib/theme'

const route = useRoute()
const siteName = ref('一丝绘画站')
const isAdminRoute = computed(() => route.path === '/admin')
const isCanvasRoute = computed(() => route.path === '/canvas' || route.path.startsWith('/canvas/'))

onMounted(async () => {
  initTheme()
  try {
    const meta = await fetchPublicMeta()
    siteName.value = meta.site_name
  } catch {
    // Use default
  }
  if (isLoggedIn()) {
    await fetchCurrentUser()
  }
})
</script>

<template>
  <div class="page-shell">
    <AppHeader v-if="!isAdminRoute" :site-name="siteName" />
    <GenerationStatsTicker v-if="!isAdminRoute && !isCanvasRoute" />
    <AnnouncementBanner v-if="!isAdminRoute && !isCanvasRoute" />
    <main class="page-content" :class="{ 'page-content--admin': isAdminRoute, 'page-content--canvas': isCanvasRoute }">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.page-content--canvas { max-width: none; padding: 16px 24px; }
@media (max-width: 700px) { .page-content--canvas { padding: 10px; } }
</style>
