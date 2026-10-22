<script setup lang="ts">
import { ArrowUpRight, Wallet } from 'lucide-vue-next'
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
import { rechargeApi } from '@/lib/recharge'
import type { CreditTransactionItem } from '@/lib/types'

const rechargeEnabled = ref(false)
const redeemInput = ref('')
const redeeming = ref(false)
const redeemFeedback = ref('')
const redeemSuccess = ref(false)

const displayName = ref('')
const usernameInput = ref('')
const usernameChangeConfirmed = ref(false)
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
  return `${window.location.origin}/gallery/${encodeURIComponent(username)}`
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
  const nextUsername = usernameInput.value.trim()
  const usernameChanged = nextUsername !== authState.user?.username
  profileFeedback.value = ''
  if (usernameChanged && !/^[a-z][a-z0-9_]{2,31}$/.test(nextUsername)) {
    profileFeedback.value = '用户名须为 3–32 位小写字母、数字或下划线，且以字母开头。'
    return
  }
  if (usernameChanged && nextUsername === 'public') {
    profileFeedback.value = '该用户名为系统保留名称，请换一个。'
    return
  }
  if (usernameChanged && !usernameChangeConfirmed.value) {
    profileFeedback.value = '修改用户名会改变画廊地址，请先确认旧链接将失效。'
    return
  }
  profileSaving.value = true
  try {
    await updateProfile({
      username: usernameChanged ? nextUsername : undefined,
      display_name: displayName.value || undefined,
      is_public: isPublic.value,
    })
    await fetchCurrentUser()
    usernameInput.value = authState.user?.username ?? ''
    usernameChangeConfirmed.value = false
    galleryCopied.value = false
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
  if (bindSending.value || bindSaving.value || bindCountdown.value > 0) return
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

function transactionTypeLabel(transactionType: string): string {
  return ({
    opening_balance: '期初余额',
    redeem: '兑换入账',
    recharge: '在线充值',
    job_reserve: '生成预扣',
    job_refund: '失败退款',
    admin_adjust: '管理员调账',
    reconciliation: '自动对账',
  } as Record<string, string>)[transactionType] ?? transactionType
}

function billingStatusLabel(status: string | null): string {
  if (!status) return '-'
  return ({ reserved: '已预扣', settled: '已结算', refunded: '已退款' } as Record<string, string>)[status] ?? status
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

onMounted(async () => {
  void rechargeApi.catalog().then((catalog) => { rechargeEnabled.value = catalog.enabled }).catch(() => {})
  await fetchCurrentUser()
  if (authState.user) {
    usernameInput.value = authState.user.username
    displayName.value = authState.user.display_name || ''
    isPublic.value = authState.user.is_public
  }
  await loadHistory()
})

onBeforeUnmount(stopBindCountdown)
</script>

<template>
  <div class="profile-page">
    <div class="profile-heading">
      <h1 class="profile-title">个人中心</h1>
      <p>管理钱包、账户资料与创作权益。</p>
    </div>

    <div class="profile-grid">
      <!-- Credits card -->
      <section class="profile-card credits-card">
        <p class="card-label wallet-label"><Wallet :size="16" aria-hidden="true" />我的钱包</p>
        <p class="credits-value">{{ authState.user?.credits ?? 0 }}<span class="credits-unit">丝</span></p>
        <p class="credits-hint">每张图片消耗模型对应灵感丝线</p>
        <router-link v-if="rechargeEnabled" to="/recharge" class="secondary-button wallet-recharge">前往充值中心<ArrowUpRight :size="16" aria-hidden="true" /></router-link>
      </section>

      <!-- Redeem card -->
      <section class="profile-card redeem-card">
        <p class="card-label">兑换灵感丝线</p>
        <p class="redeem-hint">已有兑换码？在这里兑换到钱包。</p>
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
      <section v-if="authState.user?.group" class="profile-card group-policy-card">
        <div class="group-policy-heading">
          <p class="card-label">当前用户组</p>
          <strong class="group-policy-badge">{{ authState.user.group.name }}</strong>
        </div>
        <dl class="group-policy-grid">
          <div><dt>结算倍率</dt><dd>{{ (authState.user.group.billing_multiplier_bps / 10000).toLocaleString(undefined, { maximumFractionDigits: 2 }) }}<small>×</small></dd></div>
          <div><dt>生成图保留</dt><dd>{{ authState.user.group.generated_retention_hours }}<small>小时</small></dd></div>
          <div><dt>参考图保留</dt><dd>{{ authState.user.group.reference_retention_hours }}<small>小时</small></dd></div>
          <div><dt>参考图上限</dt><dd>{{ authState.user.group.max_reference_images }}<small>张</small></dd></div>
        </dl>
        <p class="field-hint">分组策略仅影响后续创作与上传，已生成内容的价格和保留期不会变更。</p>
      </section>

      <section class="profile-card profile-edit-card">
        <p class="card-label">基本资料</p>
        <label class="field-label">
          <span>用户名</span>
          <input v-model.trim="usernameInput" type="text" class="field-input" maxlength="32" autocomplete="username" spellcheck="false" @input="usernameChangeConfirmed = false" />
        </label>
        <p class="field-hint">3–32 位小写字母、数字或下划线，以字母开头。用户名不可重复，用于画廊链接；登录建议使用邮箱。</p>
        <label v-if="usernameInput.trim() !== authState.user?.username" class="field-checkbox">
          <input v-model="usernameChangeConfirmed" type="checkbox" />
          <span>我了解修改用户名后画廊地址会变化，旧链接将失效。</span>
        </label>
        <label class="field-label">
          <span>显示名称</span>
          <input v-model="displayName" type="text" class="field-input" maxlength="128" placeholder="留空则使用用户名" />
        </label>
        <label class="field-checkbox">
          <input v-model="isPublic" type="checkbox" />
          <span>公开作品总开关（允许展示个人画廊和投稿社区）</span>
        </label>
        <p class="field-hint">
          开启后，已加入个人画廊的作品对外可见；你也可以主动投稿社区，审核通过后独立长期保存。
          关闭后个人画廊隐藏，待审投稿自动撤回；已经审核收录的社区副本继续保留。
        </p>
        <div v-if="isPublic && galleryUrl" class="gallery-link-row">
          <code class="gallery-link-url">{{ galleryUrl }}</code>
          <button class="ghost-button" @click="copyGalleryLink">
            {{ galleryCopied ? '已复制' : '复制链接' }}
          </button>
          <button class="ghost-button" @click="router.push(`/gallery/${encodeURIComponent(authState.user?.username ?? '')}`)">
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

      <section class="profile-card email-card">
        <div class="email-binding-panel" :class="{ verified: Boolean(authState.user?.email) }">
          <div class="email-binding-heading">
            <div>
              <span class="email-binding-label">账号邮箱</span>
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
            <th>模型 / 账务</th>
            <th>变动</th>
            <th>余额</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="txn in transactions" :key="txn.id">
            <td>{{ formatTime(txn.created_at) }}</td>
            <td><strong class="txn-type">{{ transactionTypeLabel(txn.transaction_type) }}</strong></td>
            <td>
              <span class="txn-model">{{ txn.model_label || '-' }}</span>
              <small v-if="txn.billing_status" class="txn-billing-status" :class="`is-${txn.billing_status}`">
                {{ billingStatusLabel(txn.billing_status) }}
              </small>
            </td>
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

<style scoped>
.profile-heading { margin-bottom: 28px; }
.profile-heading .profile-title { margin: 0 0 8px; }
.profile-heading > p { margin: 0; }
.profile-heading > p, .redeem-hint { color: var(--text-muted); font-size: 13px; line-height: 1.6; }
.wallet-label { display: flex; align-items: center; gap: 8px; }
.credits-card .wallet-label { margin: 0 0 20px; }
.credits-card .credits-value { margin: 0 0 12px; }
.credits-card .credits-hint { margin: 0; }
.credits-unit { margin-left: 10px; color: var(--text-muted); font: 400 14px var(--font-body); }
.wallet-recharge { align-self: flex-start; gap: 8px; margin-top: 20px; }
.redeem-card { display: flex; flex-direction: column; justify-content: center; }
.redeem-hint { margin-bottom: 20px; }
.redeem-row { align-items: stretch; }
.redeem-input { min-width: 0; }
.redeem-row .primary-button { min-width: 88px; min-height: 44px; }
.group-policy-card { grid-column: 1 / -1; }
.group-policy-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
.group-policy-heading .card-label { margin: 0; }
.group-policy-badge { padding: 4px 10px; border-radius: 6px; background: var(--accent-glow); color: var(--accent-strong); font-size: 12px; }
.group-policy-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px; margin: 0 0 20px; }
.group-policy-grid > div + div { border-left: 1px solid var(--border); padding-left: 24px; }
.group-policy-grid dt { color: var(--text-muted); font-size: 12px; margin-bottom: 8px; }
.group-policy-grid dd { margin: 0; color: var(--text-primary); font: 500 24px var(--font-mono); }
.group-policy-grid small { margin-left: 6px; color: var(--text-secondary); font: 400 12px var(--font-body); }
@media (max-width: 640px) {
  .group-policy-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px 16px; }
  .group-policy-grid > div + div { border: 0; padding-left: 0; }
}
</style>
