<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { fetchPublicMeta } from '@/lib/api'
import { fetchCurrentUser, isLoggedIn } from '@/lib/auth'

const siteName = ref('安落滢绘画站')

onMounted(async () => {
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
    <AppHeader :site-name="siteName" />
    <main class="page-content">
      <router-view />
    </main>
  </div>
</template>
