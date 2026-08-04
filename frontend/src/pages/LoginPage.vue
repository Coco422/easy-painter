<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { AuthApiError, login, register, requestEmailCode, resetPassword } from '@/lib/auth'
import { fetchPublicMeta } from '@/lib/api'
import type { EmailCodePurpose } from '@/lib/types'

type AuthMode = 'login' | 'register' | 'forgot'

const router = useRouter()
const mode = ref<AuthMode>('login')
const error = ref('')
const notice = ref('')
const submitting = ref(false)
const sendingCode = ref(false)
const codeCountdown = ref(0)
const registrationEnabled = ref(true)
const emailDeliveryEnabled = ref(true)
let countdownTimer: number | null = null

const loginForm = reactive({ identifier: '', password: '' })
const registerForm = reactive({ username: '', displayName: '', email: '', code: '', password: '', confirmPassword: '' })
const forgotForm = reactive({ email: '', code: '', password: '', confirmPassword: '' })

function switchMode(nextMode: AuthMode) {
  mode.value = nextMode
  error.value = ''
  notice.value = ''
  codeCountdown.value = 0
  if (countdownTimer !== null) {
    window.clearInterval(countdownTimer)
    countdownTimer = null
  }
}

function startCountdown(seconds: number) {
  codeCountdown.value = Math.max(1, Math.min(seconds, 60))
  if (countdownTimer !== null) window.clearInterval(countdownTimer)
  countdownTimer = window.setInterval(() => {
    codeCountdown.value -= 1
    if (codeCountdown.value <= 0 && countdownTimer !== null) {
      window.clearInterval(countdownTimer)
      countdownTimer = null
    }
  }, 1000)
}

async function sendCode(email: string, purpose: EmailCodePurpose) {
  if (!email.trim()) {
    error.value = '请先输入邮箱地址。'
    return
  }
  sendingCode.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await requestEmailCode(email.trim(), purpose)
    notice.value = result.message
    startCountdown(result.retry_after)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '验证码发送失败。'
    if (e instanceof AuthApiError && e.retryAfter) startCountdown(e.retryAfter)
  } finally {
    sendingCode.value = false
  }
}

async function handleLogin() {
  if (!loginForm.identifier || !loginForm.password) {
    error.value = '请输入用户名或邮箱和密码。'
    return
  }
  submitting.value = true
  error.value = ''
  notice.value = ''
  try {
    await login(loginForm.identifier, loginForm.password)
    await router.push('/')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败。'
  } finally {
    submitting.value = false
  }
}

async function handleRegister() {
  error.value = ''
  notice.value = ''
  if (!registerForm.username || !registerForm.email || !registerForm.code || !registerForm.password) {
    error.value = '请填写用户名、邮箱、验证码和密码。'
    return
  }
  if (registerForm.password.length < 6) {
    error.value = '密码至少需要 6 个字符。'
    return
  }
  if (registerForm.password !== registerForm.confirmPassword) {
    error.value = '两次输入的密码不一致。'
    return
  }
  submitting.value = true
  try {
    await register({
      username: registerForm.username,
      display_name: registerForm.displayName || undefined,
      email: registerForm.email,
      email_code: registerForm.code,
      password: registerForm.password,
    })
    await router.push('/')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '注册失败。'
  } finally {
    submitting.value = false
  }
}

async function handleResetPassword() {
  error.value = ''
  notice.value = ''
  if (!forgotForm.email || !forgotForm.code || !forgotForm.password) {
    error.value = '请填写邮箱、验证码和新密码。'
    return
  }
  if (forgotForm.password.length < 6) {
    error.value = '新密码至少需要 6 个字符。'
    return
  }
  if (forgotForm.password !== forgotForm.confirmPassword) {
    error.value = '两次输入的新密码不一致。'
    return
  }
  submitting.value = true
  try {
    await resetPassword({
      email: forgotForm.email,
      email_code: forgotForm.code,
      new_password: forgotForm.password,
    })
    switchMode('login')
    loginForm.identifier = forgotForm.email
    notice.value = '密码已更新，请使用新密码登录。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '密码重置失败。'
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => {
  if (countdownTimer !== null) window.clearInterval(countdownTimer)
})

onMounted(async () => {
  try {
    const meta = await fetchPublicMeta()
    registrationEnabled.value = meta.registration_enabled
    emailDeliveryEnabled.value = meta.email_delivery_enabled
  } catch {
    // Keep the form available and let the endpoint return the concrete error.
  }
})
</script>

<template>
  <div class="auth-page">
    <div class="auth-card auth-card-wide">
      <div class="auth-heading-row">
        <div>
          <p class="auth-kicker">Account</p>
          <h1 class="auth-title">
            {{ mode === 'login' ? '登录' : mode === 'register' ? '注册账号' : '找回密码' }}
          </h1>
        </div>
        <button v-if="mode !== 'login'" type="button" class="auth-text-button" @click="switchMode('login')">返回登录</button>
      </div>

      <form v-if="mode === 'login'" class="auth-form" @submit.prevent="handleLogin">
        <label class="auth-label">
          用户名或邮箱
          <input v-model.trim="loginForm.identifier" type="text" class="auth-input" autocomplete="username" maxlength="320" />
        </label>
        <label class="auth-label">
          密码
          <input v-model="loginForm.password" type="password" class="auth-input" autocomplete="current-password" maxlength="128" />
        </label>
        <div class="auth-inline-actions">
          <button type="button" class="auth-text-button" @click="switchMode('forgot')">忘记密码</button>
        </div>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <p v-if="notice" class="auth-notice">{{ notice }}</p>
        <button type="submit" class="auth-submit" :disabled="submitting">
          {{ submitting ? '登录中…' : '登录' }}
        </button>
        <p v-if="registrationEnabled" class="auth-switch-copy">还没有账号？<button type="button" class="auth-text-button" @click="switchMode('register')">立即注册</button></p>
      </form>

      <form v-else-if="mode === 'register'" class="auth-form" @submit.prevent="handleRegister">
        <p v-if="!emailDeliveryEnabled" class="auth-service-warning">管理员尚未配置 SMTP 邮件服务，暂时无法发送注册验证码。</p>
        <div class="auth-field-grid">
          <label class="auth-label">
            用户名
            <input v-model.trim="registerForm.username" type="text" class="auth-input" autocomplete="username" maxlength="64" placeholder="字母、数字或下划线" />
          </label>
          <label class="auth-label">
            显示名称
            <input v-model.trim="registerForm.displayName" type="text" class="auth-input" maxlength="128" placeholder="可选" />
          </label>
        </div>
        <label class="auth-label">
          邮箱
          <input v-model.trim="registerForm.email" type="email" class="auth-input" autocomplete="email" maxlength="320" />
        </label>
        <label class="auth-label">
          邮箱验证码
          <span class="auth-code-row">
            <input v-model.trim="registerForm.code" inputmode="numeric" class="auth-input" maxlength="6" autocomplete="one-time-code" />
            <button type="button" class="auth-code-button" :disabled="!emailDeliveryEnabled || sendingCode || codeCountdown > 0" @click="sendCode(registerForm.email, 'register')">
              {{ codeCountdown > 0 ? `${codeCountdown}s` : sendingCode ? '发送中…' : '发送验证码' }}
            </button>
          </span>
        </label>
        <div class="auth-field-grid">
          <label class="auth-label">
            密码
            <input v-model="registerForm.password" type="password" class="auth-input" autocomplete="new-password" maxlength="128" placeholder="至少 6 个字符" />
          </label>
          <label class="auth-label">
            确认密码
            <input v-model="registerForm.confirmPassword" type="password" class="auth-input" autocomplete="new-password" maxlength="128" />
          </label>
        </div>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <p v-if="notice" class="auth-notice">{{ notice }}</p>
        <button type="submit" class="auth-submit" :disabled="submitting">{{ submitting ? '注册中…' : '验证邮箱并注册' }}</button>
      </form>

      <form v-else class="auth-form" @submit.prevent="handleResetPassword">
        <p class="auth-description">无需输入原密码。验证注册邮箱后即可设置新密码。</p>
        <p v-if="!emailDeliveryEnabled" class="auth-service-warning">管理员尚未配置 SMTP 邮件服务，请联系管理员重置密码。</p>
        <label class="auth-label">
          注册邮箱
          <input v-model.trim="forgotForm.email" type="email" class="auth-input" autocomplete="email" maxlength="320" />
        </label>
        <label class="auth-label">
          邮箱验证码
          <span class="auth-code-row">
            <input v-model.trim="forgotForm.code" inputmode="numeric" class="auth-input" maxlength="6" autocomplete="one-time-code" />
            <button type="button" class="auth-code-button" :disabled="!emailDeliveryEnabled || sendingCode || codeCountdown > 0" @click="sendCode(forgotForm.email, 'reset_password')">
              {{ codeCountdown > 0 ? `${codeCountdown}s` : sendingCode ? '发送中…' : '发送验证码' }}
            </button>
          </span>
        </label>
        <div class="auth-field-grid">
          <label class="auth-label">
            新密码
            <input v-model="forgotForm.password" type="password" class="auth-input" autocomplete="new-password" maxlength="128" placeholder="至少 6 个字符" />
          </label>
          <label class="auth-label">
            确认新密码
            <input v-model="forgotForm.confirmPassword" type="password" class="auth-input" autocomplete="new-password" maxlength="128" />
          </label>
        </div>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <p v-if="notice" class="auth-notice">{{ notice }}</p>
        <button type="submit" class="auth-submit" :disabled="submitting">{{ submitting ? '更新中…' : '更新密码' }}</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.auth-card-wide { width: min(560px, 100%); }
.auth-heading-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.auth-kicker { margin: 0 0 6px; color: var(--accent); font: 700 11px/1.4 var(--font-mono); letter-spacing: .12em; text-transform: uppercase; }
.auth-heading-row .auth-title { margin: 0; text-align: left; }
.auth-field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.auth-code-row { display: grid; grid-template-columns: minmax(0, 1fr) 118px; gap: 8px; }
.auth-code-button { border: 1px solid var(--border-accent); border-radius: var(--radius-sm); background: var(--accent-soft); color: var(--accent); font-size: 13px; font-weight: 700; transition: background 160ms, border-color 160ms; }
.auth-code-button:hover:not(:disabled) { border-color: var(--accent); background: var(--accent-glow); }
.auth-code-button:disabled { cursor: not-allowed; opacity: .55; }
.auth-inline-actions { display: flex; justify-content: flex-end; margin-top: -4px; }
.auth-text-button { padding: 0; border: 0; background: transparent; color: var(--accent); font-size: 13px; }
.auth-text-button:hover { color: var(--accent-strong); }
.auth-switch-copy, .auth-description { margin: 0; color: var(--text-secondary); font-size: 13px; text-align: center; }
.auth-description { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-elevated); line-height: 1.65; text-align: left; }
.auth-notice { margin: 0; color: var(--success); font-size: 13px; }
.auth-service-warning { margin: 0; padding: 10px 12px; border: 1px solid rgba(180, 72, 72, .2); border-radius: var(--radius-sm); background: var(--error-soft); color: var(--error); font-size: 12px; line-height: 1.6; }
@media (max-width: 620px) {
  .auth-field-grid { grid-template-columns: 1fr; }
  .auth-code-row { grid-template-columns: minmax(0, 1fr) 108px; }
}
</style>
