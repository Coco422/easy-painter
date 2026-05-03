<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import { fetchPublicMeta } from '@/lib/api'
import { fetchCurrentUser, isLoggedIn } from '@/lib/auth'
import { initTheme } from '@/lib/theme'

const route = useRoute()
const siteName = ref('安落滢绘画站')
const isAdminRoute = computed(() => route.path === '/admin')

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
    <main class="page-content" :class="{ 'page-content--admin': isAdminRoute }">
      <router-view />
    </main>
  </div>
</template>
