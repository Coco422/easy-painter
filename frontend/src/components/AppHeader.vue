<script setup lang="ts">
defineProps<{
  siteName: string
}>()
</script>

<template>
  <header class="site-header">
    <div class="brand">
      <div class="brand-mark">❤</div>
      <div>
        <p class="brand-title">{{ siteName }}</p>
        <p class="brand-subtitle">用文字描绘属于你的安静画面</p>
      </div>
    </div>

    <nav class="header-nav">
      <a href="#create">开始创作</a>
      <a href="#gallery">最近作品</a>
      <a href="#about">项目说明</a>
    </nav>
  </header>
</template>
