<script setup lang="ts">
import { Moon, Sun, Wallet } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import logoUrl from '@/assets/brand/logo.png'
import { authState, isAdmin, isLoggedIn, logout } from '@/lib/auth'
import { themeState, toggleTheme } from '@/lib/theme'

defineProps<{
  siteName: string
}>()

const router = useRouter()
const route = useRoute()

async function handleLogout() {
  await logout()
  router.push('/')
}
</script>

<template>
  <header class="site-header">
    <div class="brand">
      <img class="brand-logo" :src="logoUrl" alt="" aria-hidden="true" />
      <router-link to="/" class="brand-title">{{ siteName }}</router-link>
    </div>
    <nav class="header-primary-nav">
      <router-link to="/" class="primary-nav-link" :class="{ active: route.path === '/' }">社区灵感</router-link>
      <router-link to="/create" class="primary-nav-link" :class="{ active: route.path === '/create' }">创作台</router-link>
      <router-link v-if="isLoggedIn()" to="/gallery" class="primary-nav-link" :class="{ active: route.path === '/gallery' }">画廊</router-link>
    </nav>
    <nav class="header-nav">
      <template v-if="isLoggedIn()">
        <router-link to="/profile" class="nav-link nav-credits" title="个人中心">
          <Wallet :size="16" />
          <span>{{ authState.user?.credits ?? 0 }}</span>
        </router-link>
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
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.brand-logo {
  width: 48px;
  height: 48px;
  flex: 0 0 auto;
  object-fit: contain;
  filter: drop-shadow(0 4px 10px rgba(196, 149, 54, 0.16));
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

.nav-credits {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  background: var(--accent-glow);
  border: 1px solid var(--border-accent);
  color: var(--accent);
  font-weight: 600;
  font-size: 0.85rem;
  text-decoration: none;
  transition: background 200ms;
}

.nav-credits:hover {
  background: var(--accent);
  color: var(--bg);
}

.header-primary-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.primary-nav-link {
  padding: 6px 14px;
  border-radius: var(--radius-sm, 6px);
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-secondary);
  text-decoration: none;
  transition: color 200ms, background 200ms;
}

.primary-nav-link:hover {
  color: var(--text);
  background: var(--accent-glow);
}

.primary-nav-link.active {
  color: var(--accent);
  background: var(--accent-glow);
  font-weight: 600;
}
</style>
