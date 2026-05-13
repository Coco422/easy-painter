<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchCurrentUser } from '@/lib/auth'
import { authState } from '@/lib/auth'
import { ApiError, changePassword, fetchCreditHistory, redeemCode, updateProfile } from '@/lib/api'
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

const router = useRouter()
const galleryUrl = computed(() => {
  const username = authState.user?.username
  if (!username) return ''
  return `${window.location.origin}/gallery/${username}`
})

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const passwordSaving = ref(false)
const passwordFeedback = ref('')
const passwordSuccess = ref(false)

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

async function handlePasswordChange() {
  passwordFeedback.value = ''
  passwordSuccess.value = false
  if (newPassword.value.length < 6) {
    passwordFeedback.value = '新密码至少需要 6 个字符。'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordFeedback.value = '两次输入的新密码不一致。'
    return
  }
  passwordSaving.value = true
  try {
    await changePassword({ old_password: oldPassword.value, new_password: newPassword.value })
    passwordFeedback.value = '密码已更新。'
    passwordSuccess.value = true
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (error) {
    passwordSuccess.value = false
    passwordFeedback.value = error instanceof Error ? error.message : '修改失败。'
  } finally {
    passwordSaving.value = false
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

      <!-- Password card -->
      <section class="profile-card password-card">
        <p class="card-label">修改密码</p>
        <label class="field-label">
          <span>原密码</span>
          <input v-model="oldPassword" type="password" class="field-input" maxlength="128" placeholder="输入当前密码" />
        </label>
        <label class="field-label">
          <span>新密码</span>
          <input v-model="newPassword" type="password" class="field-input" maxlength="128" placeholder="至少 6 个字符" />
        </label>
        <label class="field-label">
          <span>确认新密码</span>
          <input v-model="confirmPassword" type="password" class="field-input" maxlength="128" placeholder="再次输入新密码" @keyup.enter="handlePasswordChange" />
        </label>
        <div class="profile-actions">
          <button class="secondary-button" :disabled="passwordSaving" @click="handlePasswordChange">
            {{ passwordSaving ? '提交中...' : '修改密码' }}
          </button>
          <span v-if="passwordFeedback" class="profile-feedback" :class="{ success: passwordSuccess }">
            {{ passwordFeedback }}
          </span>
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
