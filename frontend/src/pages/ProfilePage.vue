<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchCurrentUser } from '@/lib/auth'
import { authState } from '@/lib/auth'
import {
  ApiError,
  bindEmail as bindVerifiedEmail,
  fetchCreditHistory,
  redeemCode,
  requestBindEmailCode,
  updateProfile,
} from '@/lib/api'
import type { CreditTransactionItem } from '@/lib/types'

const redeemInput = ref('')
const redeeming = ref(false)
const redeemFeedback = ref('')
const redeemSuccess = ref(false)

const displayName = ref('')
const isPublic = ref(false)
const profileSaving = ref(false)
const profileFeedback = ref('')
const galleryCopied = ref(false)
const bindEmailInput = ref('')
const bindCodeInput = ref('')
const bindCodeSentTo = ref('')
const bindSending = ref(false)
const bindSaving = ref(false)
const bindCountdown = ref(0)
const bindFeedback = ref('')
const bindSuccess = ref(false)
let bindCountdownTimer: number | null = null

const router = useRouter()
const galleryUrl = computed(() => {
  const username = authState.user?.username
  if (!username) return ''
  return `${window.location.origin}/gallery/${username}`
})
const normalizedBindEmail = computed(() => bindEmailInput.value.trim().toLowerCase())
const bindEmailValid = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedBindEmail.value))
const bindCodeValid = computed(() => /^\d{6}$/.test(bindCodeInput.value.trim()))

const transactions = ref<CreditTransactionItem[]>([])
const totalTransactions = ref(0)
const currentPage = ref(1)
const loadingHistory = ref(false)

async function loadHistory(page = 1) {
  loadingHistory.value = true
  try {
    const data = await fetchCreditHistory(page)
    transactions.value = data.items
    totalTransactions.value = data.total
    currentPage.value = page
  } catch {
    // silent
  } finally {
    loadingHistory.value = false
  }
}

async function handleRedeem() {
  const code = redeemInput.value.trim()
  if (!code) {
    redeemFeedback.value = '请输入兑换码。'
    redeemSuccess.value = false
    return
  }
  redeeming.value = true
  redeemFeedback.value = ''
  try {
    const result = await redeemCode(code)
    redeemFeedback.value = `兑换成功！获得 ${result.added} 丝，当前余额 ${result.credits} 丝。`
    redeemSuccess.value = true
    redeemInput.value = ''
    await fetchCurrentUser()
    await loadHistory()
  } catch (error) {
    redeemSuccess.value = false
    redeemFeedback.value = error instanceof Error ? error.message : '兑换失败。'
  } finally {
    redeeming.value = false
  }
}

async function handleSaveProfile() {
  profileSaving.value = true
  profileFeedback.value = ''
  try {
    await updateProfile({
      display_name: displayName.value || undefined,
      is_public: isPublic.value,
    })
    await fetchCurrentUser()
    profileFeedback.value = '资料已更新。'
  } catch (error) {
    profileFeedback.value = error instanceof Error ? error.message : '保存失败。'
  } finally {
    profileSaving.value = false
  }
}

function stopBindCountdown() {
  if (bindCountdownTimer !== null) {
    window.clearInterval(bindCountdownTimer)
    bindCountdownTimer = null
  }
}

function startBindCountdown(seconds: number) {
  stopBindCountdown()
  bindCountdown.value = Math.max(1, seconds)
  bindCountdownTimer = window.setInterval(() => {
    bindCountdown.value -= 1
    if (bindCountdown.value <= 0) stopBindCountdown()
  }, 1000)
}

function handleBindEmailInput() {
  if (bindCodeSentTo.value && normalizedBindEmail.value !== bindCodeSentTo.value) {
    bindCodeSentTo.value = ''
    bindCodeInput.value = ''
    bindFeedback.value = '邮箱已变更，请重新发送验证码。'
    bindSuccess.value = false
  }
}

async function handleRequestBindCode() {
  if (!bindEmailValid.value) {
    bindFeedback.value = '请输入有效的邮箱地址。'
    bindSuccess.value = false
    return
  }
  bindSending.value = true
  bindFeedback.value = ''
  bindSuccess.value = false
  try {
    const result = await requestBindEmailCode(normalizedBindEmail.value)
    bindCodeSentTo.value = normalizedBindEmail.value
    bindFeedback.value = `验证码已发送至 ${bindCodeSentTo.value}。`
    bindSuccess.value = true
    startBindCountdown(result.retry_after)
  } catch (error) {
    bindFeedback.value = error instanceof Error ? error.message : '验证码发送失败。'
    if (error instanceof ApiError && error.status === 429) {
      startBindCountdown(error.retryAfter ?? 60)
    }
  } finally {
    bindSending.value = false
  }
}

async function handleBindEmail() {
  if (!bindEmailValid.value) {
    bindFeedback.value = '请输入有效的邮箱地址。'
    bindSuccess.value = false
    return
  }
  if (normalizedBindEmail.value !== bindCodeSentTo.value) {
    bindFeedback.value = '请先向当前邮箱发送验证码。'
    bindSuccess.value = false
    return
  }
  if (!bindCodeValid.value) {
    bindFeedback.value = '请输入 6 位数字验证码。'
    bindSuccess.value = false
    return
  }

  bindSaving.value = true
  bindFeedback.value = ''
  bindSuccess.value = false
  try {
    await bindVerifiedEmail(normalizedBindEmail.value, bindCodeInput.value.trim())
    await fetchCurrentUser()
    bindFeedback.value = '邮箱已验证并绑定。'
    bindSuccess.value = true
    bindCodeInput.value = ''
    bindCodeSentTo.value = ''
    stopBindCountdown()
    bindCountdown.value = 0
  } catch (error) {
    bindFeedback.value = error instanceof Error ? error.message : '邮箱绑定失败。'
  } finally {
    bindSaving.value = false
  }
}

async function copyGalleryLink() {
  if (!galleryUrl.value) return
  try {
    await navigator.clipboard.writeText(galleryUrl.value)
    galleryCopied.value = true
    setTimeout(() => { galleryCopied.value = false }, 2000)
  } catch {
    const input = document.createElement('input')
    input.value = galleryUrl.value
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    document.body.removeChild(input)
    galleryCopied.value = true
    setTimeout(() => { galleryCopied.value = false }, 2000)
  }
}

function formatReason(reason: string): string {
  if (reason.startsWith('redeem:')) return `兑换码 ${reason.slice(7)}`
  if (reason.startsWith('job:')) return '生成图片'
  if (reason === 'admin:adjust') return '管理员调整'
  return reason
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

onMounted(async () => {
  await fetchCurrentUser()
  if (authState.user) {
    displayName.value = authState.user.display_name || ''
    isPublic.value = authState.user.is_public
  }
  await loadHistory()
})

onBeforeUnmount(stopBindCountdown)
</script>

<template>
  <div class="profile-page">
    <h1 class="profile-title">个人中心</h1>

    <div class="profile-grid">
      <!-- Credits card -->
      <section class="profile-card credits-card">
        <p class="card-label">灵感丝线余额</p>
        <p class="credits-value">{{ authState.user?.credits ?? 0 }}</p>
        <p class="credits-hint">每张图片消耗模型对应灵感丝线</p>
      </section>

      <!-- Redeem card -->
      <section class="profile-card redeem-card">
        <p class="card-label">兑换灵感丝线</p>
        <div class="redeem-row">
          <input
            v-model="redeemInput"
            type="text"
            class="redeem-input"
            placeholder="输入兑换码"
            maxlength="64"
            :disabled="redeeming"
            @keyup.enter="handleRedeem"
          />
          <button class="primary-button" :disabled="redeeming" @click="handleRedeem">
            {{ redeeming ? '兑换中...' : '兑换' }}
          </button>
        </div>
        <p v-if="redeemFeedback" class="redeem-feedback" :class="{ success: redeemSuccess }">
          {{ redeemFeedback }}
        </p>
      </section>

      <!-- Profile card -->
      <section class="profile-card profile-edit-card">
        <p class="card-label">基本资料</p>
        <label class="field-label">
          <span>显示名称</span>
          <input v-model="displayName" type="text" class="field-input" maxlength="128" placeholder="留空则使用用户名" />
        </label>
        <div class="email-binding-panel" :class="{ verified: Boolean(authState.user?.email) }">
          <div class="email-binding-heading">
            <div>
              <span class="email-binding-label">验证邮箱</span>
              <strong>{{ authState.user?.email ? '邮箱已绑定' : '绑定邮箱以保护账号' }}</strong>
            </div>
            <span class="email-status-tag">{{ authState.user?.email ? '已验证' : '未绑定' }}</span>
          </div>

          <template v-if="authState.user?.email">
            <code class="verified-email">{{ authState.user.email }}</code>
            <p class="email-binding-hint">已绑定邮箱不能在个人中心自行更换；如需更换，请联系管理员处理。</p>
          </template>

          <template v-else>
            <p class="email-binding-hint">验证码会发送到目标邮箱。服务端会按邮箱、IP 和当前账号限制发送频率。</p>
            <label class="field-label email-binding-field">
              <span>邮箱地址</span>
              <span class="email-field-row">
                <input
                  v-model="bindEmailInput"
                  type="email"
                  class="field-input"
                  autocomplete="email"
                  maxlength="320"
                  placeholder="name@example.com"
                  :disabled="bindSaving"
                  @input="handleBindEmailInput"
                  @keyup.enter="handleRequestBindCode"
                />
                <button
                  type="button"
                  class="email-code-button"
                  :disabled="bindSending || bindSaving || bindCountdown > 0"
                  @click="handleRequestBindCode"
                >
                  {{ bindCountdown > 0 ? `${bindCountdown}s 后重试` : bindSending ? '发送中…' : '发送验证码' }}
                </button>
              </span>
            </label>
            <label class="field-label email-binding-field">
              <span>邮箱验证码</span>
              <span class="email-field-row">
                <input
                  v-model="bindCodeInput"
                  inputmode="numeric"
                  autocomplete="one-time-code"
                  class="field-input email-code-input"
                  maxlength="6"
                  placeholder="6 位数字"
                  :disabled="bindSaving"
                  @keyup.enter="handleBindEmail"
                />
                <button
                  type="button"
                  class="secondary-button email-bind-button"
                  :disabled="bindSaving || !bindCodeValid || normalizedBindEmail !== bindCodeSentTo"
                  @click="handleBindEmail"
                >
                  {{ bindSaving ? '验证中…' : '验证并绑定' }}
                </button>
              </span>
            </label>
          </template>

          <p v-if="bindFeedback" class="email-binding-feedback" :class="{ success: bindSuccess }">
            {{ bindFeedback }}
          </p>
        </div>
        <label class="field-checkbox">
          <input v-model="isPublic" type="checkbox" />
          <span>公开画廊（其他用户可以查看你的作品）</span>
        </label>
        <p class="field-hint">
          开启后，你将拥有一个专属的作品集页面。你可以在作品详情中将图片「发布」到公开画廊，
          已发布的作品会展示在你的公开主页上，任何人均可通过链接访问（无需登录）。
        </p>
        <div v-if="isPublic && galleryUrl" class="gallery-link-row">
          <code class="gallery-link-url">{{ galleryUrl }}</code>
          <button class="ghost-button" @click="copyGalleryLink">
            {{ galleryCopied ? '已复制' : '复制链接' }}
          </button>
          <button class="ghost-button" @click="router.push(`/gallery/${authState.user?.username}`)">
            前往画廊
          </button>
        </div>
        <div class="profile-actions">
          <button class="secondary-button" :disabled="profileSaving" @click="handleSaveProfile">
            {{ profileSaving ? '保存中...' : '保存' }}
          </button>
          <span v-if="profileFeedback" class="profile-feedback">{{ profileFeedback }}</span>
        </div>
      </section>

    </div>
    <section class="profile-card history-card">
      <p class="card-label">消费记录</p>
      <div v-if="loadingHistory" class="history-loading">加载中...</div>
      <div v-else-if="transactions.length === 0" class="history-empty">暂无记录</div>
      <table v-else class="history-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>变动</th>
            <th>余额</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="txn in transactions" :key="txn.created_at + txn.reason">
            <td>{{ formatTime(txn.created_at) }}</td>
            <td>{{ formatReason(txn.reason) }}</td>
            <td :class="txn.amount > 0 ? 'txn-positive' : 'txn-negative'">
              {{ txn.amount > 0 ? '+' : '' }}{{ txn.amount }}
            </td>
            <td>{{ txn.balance_after }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="totalTransactions > 20" class="history-pagination">
        <button
          class="ghost-button"
          :disabled="currentPage <= 1"
          @click="loadHistory(currentPage - 1)"
        >上一页</button>
        <span>{{ currentPage }} / {{ Math.ceil(totalTransactions / 20) }}</span>
        <button
          class="ghost-button"
          :disabled="currentPage >= Math.ceil(totalTransactions / 20)"
          @click="loadHistory(currentPage + 1)"
        >下一页</button>
      </div>
    </section>
  </div>
</template>
