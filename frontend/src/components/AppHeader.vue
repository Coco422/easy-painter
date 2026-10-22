<script setup lang="ts">
import { ChevronDown, Heart, History, Images, LogOut, Moon, Plug, Settings, Sun, UserRound, Wallet } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import logoUrl from '@/assets/brand/logo.png'
import VersionReleaseDialog from '@/components/VersionReleaseDialog.vue'
import { authState, isAdmin, isLoggedIn, logout } from '@/lib/auth'
import { themeState, toggleTheme } from '@/lib/theme'

defineProps<{ siteName: string; relatedSitesEnabled: boolean }>()
const router = useRouter()
const route = useRoute()
const logoutError = ref('')
const accountMenu = ref<HTMLDetailsElement | null>(null)

function closeMenu() { if (accountMenu.value) accountMenu.value.open = false }
function dismissMenu(event: PointerEvent | KeyboardEvent) {
  if (!(event.target instanceof Node) || accountMenu.value?.contains(event.target)) {
    if (event instanceof KeyboardEvent && event.key === 'Escape') {
      closeMenu()
      accountMenu.value?.querySelector('summary')?.focus()
    }
    return
  }
  if (event.target instanceof Element && event.target.closest('.version-dialog-backdrop')) return
  if (event instanceof PointerEvent || event.key === 'Escape') closeMenu()
}
watch(() => route.fullPath, closeMenu)
watch(() => authState.sessionId, closeMenu)
onMounted(() => {
  document.addEventListener('pointerdown', dismissMenu)
  document.addEventListener('keydown', dismissMenu)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', dismissMenu)
  document.removeEventListener('keydown', dismissMenu)
})
async function handleLogout() {
  closeMenu()
  logoutError.value = ''
  try { await logout(); await router.push('/') }
  catch (error) { logoutError.value = error instanceof Error ? error.message : '退出未能同步到服务器，请重试。' }
}
</script>

<template>
  <header class="site-header">
    <router-link to="/" class="brand" :aria-label="siteName + '首页'">
      <img class="brand-logo" :src="logoUrl" alt="" aria-hidden="true" />
      <span class="brand-title">{{ siteName }}</span>
    </router-link>
    <nav class="header-primary-nav" aria-label="主导航">
      <router-link to="/" class="primary-nav-link" :class="{ active: route.path === '/' }">社区灵感</router-link>
      <router-link to="/create" class="primary-nav-link" :class="{ active: route.path === '/create' }">创作台</router-link>
      <router-link to="/canvas" class="primary-nav-link" :class="{ active: route.path === '/canvas' || route.path.startsWith('/canvas/') }">无限画布</router-link>
    </nav>
    <nav class="header-nav" aria-label="账户与设置">
      <router-link v-if="isLoggedIn()" to="/profile" class="nav-credits" title="钱包与个人中心" :aria-label="`钱包余额 ${authState.user?.credits ?? 0} 丝，个人中心`">
        <Wallet :size="16" aria-hidden="true" /><span>{{ authState.user?.credits ?? 0 }}</span>
      </router-link>
      <router-link v-else to="/login" class="nav-link">登录</router-link>
      <details ref="accountMenu" class="account-menu">
        <summary :aria-label="isLoggedIn() ? '账户菜单' : '更多功能'">
          <UserRound :size="17" aria-hidden="true" /><span class="account-name">{{ isLoggedIn() ? authState.user?.display_name || authState.user?.username || '我的账户' : '更多' }}</span><ChevronDown :size="14" aria-hidden="true" />
        </summary>
        <div class="account-menu-panel">
          <div class="account-menu-links" @click="closeMenu">
            <template v-if="isLoggedIn()">
              <router-link to="/profile"><UserRound :size="16" />个人中心</router-link>
              <router-link to="/history"><History :size="16" />生图历史</router-link>
              <router-link to="/gallery"><Images :size="16" />我的画廊</router-link>
              <router-link to="/favorites"><Heart :size="16" />我的收藏</router-link>
            </template>
            <template v-if="relatedSitesEnabled">
            <a href="https://88888888.dog/home" target="_blank" rel="noopener noreferrer"><Plug :size="16" />88dog 中转主站 ↗</a>
            <a href="https://doc.88888888.dog/" target="_blank" rel="noopener noreferrer"><Images :size="16" />使用文档 ↗</a>
            <a href="https://getplus.88888888.dog/" target="_blank" rel="noopener noreferrer"><Wallet :size="16" />会员代充 ↗</a>
            </template>
            <router-link to="/mcp"><Plug :size="16" />连接 Agent</router-link>
            <router-link v-if="isAdmin()" to="/admin"><Settings :size="16" />管理后台</router-link>
          </div>
          <div class="account-menu-footer">
            <VersionReleaseDialog v-if="relatedSitesEnabled" />
            <button v-if="isLoggedIn()" type="button" @click="handleLogout"><LogOut :size="14" />退出登录</button>
          </div>
        </div>
      </details>
      <button class="theme-toggle" :title="themeState.current === 'dark' ? '切换到浅色模式' : '切换到深色模式'" @click="toggleTheme">
        <Sun v-if="themeState.current === 'dark'" :size="18" /><Moon v-else :size="18" />
      </button>
    </nav>
  </header>
  <p v-if="logoutError" class="feedback-banner" role="alert">{{ logoutError }} <button class="ghost-button" @click="handleLogout">重试退出</button></p>
</template>

<style scoped>
.site-header { max-width:1280px; gap:24px; padding-block:16px; z-index:5; }
.brand { display:flex; align-items:center; gap:10px; flex-shrink:0; text-decoration:none; min-width:0; }
.brand-title { white-space:nowrap; font-size:21px; }
.brand-logo { width:40px; height:40px; object-fit:contain; flex-shrink:0; }
.header-primary-nav { display:flex; flex:1; align-items:center; justify-content:center; gap:8px; }
.primary-nav-link { display:inline-flex; align-items:center; justify-content:center; min-height:36px; padding:0 14px; border-radius:6px; font-size:14px; font-weight:500; color:var(--text-secondary); text-decoration:none; white-space:nowrap; transition:background 160ms,color 160ms; }
.primary-nav-link:hover { color:var(--text-primary); background:var(--bg-hover); }
.primary-nav-link.active { color:var(--accent-strong); background:var(--accent-glow); }
.header-nav { display:flex; align-items:center; gap:12px; flex-shrink:0; }
.nav-credits { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:36px; padding:0 12px; color:var(--accent-strong); border:1px solid var(--border-accent); border-radius:6px; background:var(--accent-glow); text-decoration:none; font:600 13px var(--font-mono); }
.account-menu { position:relative; }
.account-menu summary { display:flex; align-items:center; gap:8px; min-height:36px; padding:0 8px; border-radius:6px; list-style:none; cursor:pointer; color:var(--text-secondary); font-size:13px; }
.account-menu summary::-webkit-details-marker { display:none; }
.account-menu summary:hover,.account-menu[open] summary { color:var(--text-primary); background:var(--bg-hover); }
.account-name { max-width:96px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.account-menu-panel { position:absolute; top:calc(100% + 12px); right:0; width:220px; padding:8px; border:1px solid var(--border); border-radius:12px; background:var(--bg-surface); box-shadow:var(--shadow-lg); z-index:60; }
.account-menu-links { display:grid; gap:2px; }
.account-menu-links a,.account-menu-footer > button { display:flex; align-items:center; gap:10px; min-height:38px; padding:0 12px; border:0; border-radius:6px; background:transparent; color:var(--text-secondary); font:inherit; font-size:13px; text-decoration:none; cursor:pointer; }
.account-menu-links a:hover,.account-menu-footer > button:hover { color:var(--accent-strong); background:var(--bg-hover); }
.account-menu-footer { display:flex; align-items:center; justify-content:space-between; gap:4px; margin-top:8px; padding-top:8px; border-top:1px solid var(--border); }
.account-menu-footer > button { padding-inline:6px; font-size:12px; }
.theme-toggle { display:grid; place-items:center; width:36px; height:36px; border:1px solid var(--border); border-radius:6px; background:transparent; color:var(--text-secondary); cursor:pointer; }
.theme-toggle:hover { color:var(--accent-strong); background:var(--bg-hover); }
summary:focus-visible,.theme-toggle:focus-visible,a:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
@media(max-width:900px) {
  .site-header { flex-wrap:wrap; gap:12px; }
  .brand { flex:1; }
  .header-primary-nav { order:3; flex:1 0 100%; padding-top:12px; border-top:1px solid var(--border); }
}
@media(max-width:520px) {
  .site-header { padding:12px 16px; column-gap:8px; }
  .brand { gap:8px; }
  .brand-title { font-size:18px; }
  .brand-logo { width:32px; height:32px; }
  .header-nav { gap:6px; }
  .account-name { display:none; }
  .account-menu summary { gap:4px; padding-inline:4px; }
  .nav-credits { padding-inline:8px; }
  .theme-toggle { width:32px; height:32px; }
  .primary-nav-link { font-size:13px; padding-inline:12px; }
  .account-menu-panel { right:-38px; }
}
</style>
