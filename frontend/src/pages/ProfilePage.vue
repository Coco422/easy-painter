<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchCurrentUser } from '@/lib/auth'
import { authState } from '@/lib/auth'
import { ApiError, fetchCreditHistory, redeemCode, updateProfile } from '@/lib/api'
import type { CreditTransactionItem } from '@/lib/types'

const redeemInput = ref('')
const redeeming = ref(false)
const redeemFeedback = ref('')
const redeemSuccess = ref(false)

const displayName = ref('')
const isPublic = ref(false)
const profileSaving = ref(false)
const profileFeedback = ref('')

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
        <label class="field-checkbox">
          <input v-model="isPublic" type="checkbox" />
          <span>公开画廊（其他用户可以查看你的作品）</span>
        </label>
        <div class="profile-actions">
          <button class="secondary-button" :disabled="profileSaving" @click="handleSaveProfile">
            {{ profileSaving ? '保存中...' : '保存' }}
          </button>
          <span v-if="profileFeedback" class="profile-feedback">{{ profileFeedback }}</span>
        </div>
      </section>
    </div>

    <!-- Credit history -->
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
