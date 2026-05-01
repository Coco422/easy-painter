<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '@/lib/auth'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码。'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    await login(username.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败。'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1 class="auth-title">登录</h1>
      <form class="auth-form" @submit.prevent="handleLogin">
        <label class="auth-label">
          用户名
          <input v-model="username" type="text" class="auth-input" autocomplete="username" maxlength="64" />
        </label>
        <label class="auth-label">
          密码
          <input v-model="password" type="password" class="auth-input" autocomplete="current-password" maxlength="128" />
        </label>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <button type="submit" class="auth-submit" :disabled="submitting">
          {{ submitting ? '登录中…' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>
