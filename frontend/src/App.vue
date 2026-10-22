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
const relatedSitesEnabled = ref(false)
const isAdminRoute = computed(() => route.path === '/admin')
const isCanvasRoute = computed(() => route.path === '/canvas' || route.path.startsWith('/canvas/'))
const isAccountRoute = computed(() => route.path === '/profile' || route.path === '/recharge' || route.path.startsWith('/recharge/'))

onMounted(async () => {
  initTheme()
  try {
    const meta = await fetchPublicMeta()
    siteName.value = meta.site_name
    relatedSitesEnabled.value = meta.related_sites_enabled ?? true
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
    <AppHeader v-if="!isAdminRoute" :site-name="siteName" :related-sites-enabled="relatedSitesEnabled" />
    <GenerationStatsTicker v-if="!isAdminRoute && !isCanvasRoute && !isAccountRoute" />
    <AnnouncementBanner v-if="!isAdminRoute && !isCanvasRoute" />
    <main class="page-content" :class="{ 'page-content--admin': isAdminRoute, 'page-content--canvas': isCanvasRoute }">
      <router-view />
    </main>
    <nav v-if="relatedSitesEnabled && !isAdminRoute && !isCanvasRoute" class="related-sites" aria-label="88dog 站点导航">
      <a href="https://88888888.dog/home" target="_blank" rel="noopener noreferrer">88dog 中转主站 ↗</a>
      <a href="https://doc.88888888.dog/" target="_blank" rel="noopener noreferrer">使用文档 ↗</a>
      <a href="https://getplus.88888888.dog/" target="_blank" rel="noopener noreferrer">会员代充 ↗</a>
    </nav>
  </div>
</template>

<style scoped>
.related-sites { display:flex; flex-wrap:wrap; justify-content:center; gap:12px 24px; padding:24px 16px; border-top:1px solid var(--border); color:var(--text-secondary); font-size:13px; }
.related-sites a { color:inherit; text-decoration:none; }
.related-sites a:hover { color:var(--accent-strong); }
.related-sites a:focus-visible { outline:2px solid var(--accent); outline-offset:4px; }
.page-content--canvas { max-width: none; padding: 16px 24px; }
@media (max-width: 700px) { .page-content--canvas { padding: 10px; } }
</style>
