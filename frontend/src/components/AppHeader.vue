<script setup lang="ts">
import { Moon, Sun } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { authState, isAdmin, isLoggedIn, logout } from '@/lib/auth'
import { themeState, toggleTheme } from '@/lib/theme'

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
      <span class="brand-mark" aria-hidden="true"></span>
      <router-link to="/" class="brand-title">{{ siteName }}</router-link>
    </div>
    <nav class="header-nav">
      <template v-if="isLoggedIn()">
        <span class="nav-user">{{ authState.user?.username }}</span>
        <router-link v-if="authState.user?.is_public" :to="`/gallery/${authState.user.username}`" class="nav-link">
          公开画廊
        </router-link>
        <router-link v-if="isAdmin()" to="/admin" class="nav-link nav-admin">管理</router-link>
        <button class="nav-link nav-logout" @click="handleLogout">退出</button>
      </template>
      <template v-else>
        <router-link to="/login" class="nav-link">登录</router-link>
      </template>
      <button class="theme-toggle" :title="themeState.current === 'dark' ? '切换到浅色模式' : '切换到深色模式'" @click="toggleTheme">
        <Sun v-if="themeState.current === 'dark'" :size="18" />
        <Moon v-else :size="18" />
      </button>
    </nav>
  </header>
</template>

<style scoped>
.brand-mark {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--accent);
  transform: rotate(45deg);
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 200ms, background 200ms, border-color 200ms;
  margin-left: 4px;
}

.theme-toggle:hover {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--accent-glow);
}
</style>
