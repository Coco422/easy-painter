<script setup lang="ts">
import { useRouter } from 'vue-router'
import { authState, isAdmin, isLoggedIn, logout } from '@/lib/auth'

defineProps<{
  siteName: string
}>()

const router = useRouter()

async function handleLogout() {
  await logout()
  router.push('/')
}
</script>

<template>
  <header class="site-header">
    <div class="brand">
      <router-link to="/" class="brand-title">{{ siteName }}</router-link>
    </div>
    <nav class="header-nav">
      <template v-if="isLoggedIn()">
        <span class="nav-user">{{ authState.user?.username }}</span>
        <router-link v-if="authState.user?.is_public" :to="`/gallery/${authState.user.username}`" class="nav-link">
          我的公开画廊
        </router-link>
        <router-link v-if="isAdmin()" to="/admin" class="nav-link nav-admin">管理</router-link>
        <button class="nav-link nav-logout" @click="handleLogout">退出</button>
      </template>
      <template v-else>
        <router-link to="/login" class="nav-link">登录</router-link>
      </template>
    </nav>
  </header>
</template>
