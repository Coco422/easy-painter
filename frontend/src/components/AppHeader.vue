<script setup lang="ts">
defineProps<{
  siteName: string
}>()
</script>

<template>
  <header class="site-header">
    <div class="brand">
      <p class="brand-title">{{ siteName }}</p>
    </div>
  </header>
</template>
