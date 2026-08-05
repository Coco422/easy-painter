<script setup lang="ts">
import { computed, defineAsyncComponent, reactive, ref, type Component } from 'vue'
import {
  darkTheme,
  NButton,
  NCard,
  NConfigProvider,
  NDialogProvider,
  NForm,
  NFormItem,
  NInput,
  NMessageProvider,
  type FormInst,
  type FormRules,
  type GlobalThemeOverrides,
} from 'naive-ui'
import { Cpu, Gauge, ListTodo, LogOut, Megaphone, Menu, Server, Users, Wallet } from 'lucide-vue-next'

import { adminLogout, adminVerify, authState } from '@/lib/auth'
import { themeState } from '@/lib/theme'

type SectionKey = 'overview' | 'providers' | 'models' | 'users' | 'jobs' | 'billing' | 'announcements'

const sectionComponents: Record<SectionKey, Component> = {
  overview: defineAsyncComponent(() => import('./sections/AdminOverview.vue')),
  providers: defineAsyncComponent(() => import('./sections/AdminProviders.vue')),
  models: defineAsyncComponent(() => import('./sections/AdminModels.vue')),
  users: defineAsyncComponent(() => import('./sections/AdminUsers.vue')),
  jobs: defineAsyncComponent(() => import('./sections/AdminJobs.vue')),
  billing: defineAsyncComponent(() => import('./sections/AdminBilling.vue')),
  announcements: defineAsyncComponent(() => import('./sections/AdminAnnouncements.vue')),
}

const navItems = [
  { key: 'overview' as const, label: '总览', icon: Gauge },
  { key: 'providers' as const, label: '上游管理', icon: Server },
  { key: 'models' as const, label: '模型管理', icon: Cpu },
  { key: 'users' as const, label: '用户管理', icon: Users },
  { key: 'jobs' as const, label: '任务管理', icon: ListTodo },
  { key: 'billing' as const, label: '计费管理', icon: Wallet },
  { key: 'announcements' as const, label: '通知管理', icon: Megaphone },
]

const activeSection = ref<SectionKey>('overview')
const sidebarOpen = ref(false)
const authenticated = computed(() => Boolean(authState.adminToken))
const activeComponent = computed(() => sectionComponents[activeSection.value])
const activeLabel = computed(() => navItems.find((item) => item.key === activeSection.value)?.label ?? '管理后台')

const authFormRef = ref<FormInst | null>(null)
const authForm = reactive({ secretKey: '' })
const authRules: FormRules = {
  secretKey: { required: true, message: '请输入管理员密钥', trigger: ['input', 'blur'] },
}
const verifying = ref(false)
const verifyError = ref('')

const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const dark = themeState.current === 'dark'
  return {
    common: {
      primaryColor: dark ? '#d4a853' : '#c49536',
      primaryColorHover: dark ? '#e0b866' : '#a87d28',
      primaryColorPressed: dark ? '#c49536' : '#916b20',
      primaryColorSuppl: dark ? '#d4a853' : '#c49536',
      bodyColor: dark ? '#0c0c0e' : '#f8f5ee',
      cardColor: dark ? '#161618' : '#ffffff',
      modalColor: dark ? '#161618' : '#ffffff',
      popoverColor: dark ? '#161618' : '#ffffff',
      tableColor: dark ? '#161618' : '#ffffff',
      inputColor: dark ? '#1a1a1e' : '#faf8f3',
      borderColor: dark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.08)',
      dividerColor: dark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.08)',
      textColorBase: dark ? '#f0ece4' : '#2c2518',
      textColor1: dark ? '#f0ece4' : '#2c2518',
      textColor2: dark ? '#a09888' : '#6b5d4a',
      textColor3: dark ? '#6b6358' : '#9c8e7a',
      borderRadius: '6px',
      borderRadiusSmall: '4px',
      fontFamily: 'var(--font-body)',
      fontFamilyMono: 'var(--font-mono)',
      boxShadow1: dark ? '0 2px 8px rgba(0, 0, 0, 0.3)' : '0 2px 8px rgba(80, 60, 30, 0.06)',
      boxShadow2: dark ? '0 8px 32px rgba(0, 0, 0, 0.4)' : '0 8px 32px rgba(80, 60, 30, 0.1)',
      cubicBezierEaseInOut: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
    },
  }
})

async function handleVerify() {
  verifyError.value = ''
  try {
    await authFormRef.value?.validate()
  } catch {
    return
  }
  verifying.value = true
  try {
    await adminVerify(authForm.secretKey)
    authForm.secretKey = ''
  } catch (error) {
    verifyError.value = error instanceof Error ? error.message : '验证失败。'
  } finally {
    verifying.value = false
  }
}

function selectSection(section: SectionKey) {
  activeSection.value = section
  sidebarOpen.value = false
}

function handleLogout() {
  adminLogout()
  sidebarOpen.value = false
  verifyError.value = ''
}

function handleAuthExpired() {
  adminLogout()
  sidebarOpen.value = false
  verifyError.value = '管理员密钥已过期，请重新验证。'
}
</script>

<template>
  <NConfigProvider
    :theme="themeState.current === 'dark' ? darkTheme : null"
    :theme-overrides="themeOverrides"
  >
    <NMessageProvider>
      <NDialogProvider>
        <div class="admin-page">
          <div v-if="!authenticated" class="admin-auth-wrap">
            <NCard class="admin-auth-card" title="管理后台" size="large" :bordered="true">
              <NForm ref="authFormRef" :model="authForm" :rules="authRules" @submit.prevent="handleVerify">
                <NFormItem label="管理员密钥" path="secretKey" :feedback="verifyError || undefined" :validation-status="verifyError ? 'error' : undefined">
                  <NInput
                    v-model:value="authForm.secretKey"
                    type="password"
                    show-password-on="click"
                    placeholder="请输入管理员密钥"
                    autocomplete="current-password"
                    @keyup.enter="handleVerify"
                  />
                </NFormItem>
                <NButton type="primary" block :loading="verifying" @click="handleVerify">验证</NButton>
              </NForm>
            </NCard>
          </div>

          <div v-else class="admin-layout">
            <header class="admin-topbar">
              <button type="button" class="admin-hamburger" aria-label="打开导航" @click="sidebarOpen = !sidebarOpen">
                <Menu :size="19" />
              </button>
              <div class="admin-topbar-copy">
                <span>管理后台</span>
                <strong>{{ activeLabel }}</strong>
              </div>
              <NButton quaternary size="small" class="admin-logout-btn" @click="handleLogout">
                <template #icon><LogOut :size="16" /></template>
                退出管理
              </NButton>
            </header>

            <aside class="admin-sidebar" :class="{ open: sidebarOpen }">
              <div class="admin-sidebar-brand">Easy Painter</div>
              <nav class="admin-nav" aria-label="后台导航">
                <button
                  v-for="item in navItems"
                  :key="item.key"
                  type="button"
                  class="admin-nav-item"
                  :class="{ active: activeSection === item.key }"
                  @click="selectSection(item.key)"
                >
                  <component :is="item.icon" :size="17" />
                  <span>{{ item.label }}</span>
                </button>
              </nav>
            </aside>

            <button
              v-if="sidebarOpen"
              type="button"
              class="admin-sidebar-backdrop"
              aria-label="关闭导航"
              @click="sidebarOpen = false"
            />

            <main class="admin-main">
              <KeepAlive>
                <component :is="activeComponent" @auth-expired="handleAuthExpired" />
              </KeepAlive>
            </main>
          </div>
        </div>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
