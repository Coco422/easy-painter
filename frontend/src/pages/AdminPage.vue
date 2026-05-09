<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Server, Cpu, Users, ListTodo, LogOut, Menu, X, Eye, Wallet, Ticket, ArrowRightLeft, Trash2 } from 'lucide-vue-next'
import {
  adminAdjustCredits,
  adminBatchDeleteJobs,
  adminCreateModel,
  adminCreateProvider,
  adminCreateUser,
  adminDeleteJob,
  adminDeleteModel,
  adminDeleteProvider,
  adminDeleteUser,
  adminFetchCodes,
  adminFetchJobs,
  adminFetchModels,
  adminFetchProviders,
  adminFetchTransactions,
  adminFetchUsers,
  adminGenerateCodes,
  adminUpdateModel,
  adminUpdateProvider,
  adminUpdateUser,
} from '@/lib/api'
import { adminLogout, adminVerify, isAdmin } from '@/lib/auth'
import { ApiError } from '@/lib/api'
import type { AdminJobItem, CreditTransactionItem, ModelConfig, RedemptionCodeItem, UpstreamProvider, UserInfo } from '@/lib/types'

const secretKey = ref('')
const verifyError = ref('')
const verifying = ref(false)

type SectionKey = 'providers' | 'models' | 'users' | 'jobs' | 'billing'
const activeSection = ref<SectionKey>('providers')
const sidebarOpen = ref(false)

const navItems: { key: SectionKey; label: string; icon: typeof Server }[] = [
  { key: 'providers', label: '上游管理', icon: Server },
  { key: 'models', label: '模型管理', icon: Cpu },
  { key: 'users', label: '用户管理', icon: Users },
  { key: 'jobs', label: '任务管理', icon: ListTodo },
  { key: 'billing', label: '计费管理', icon: Wallet },
]

const jobs = ref<AdminJobItem[]>([])
const users = ref<UserInfo[]>([])
const providers = ref<UpstreamProvider[]>([])
const models = ref<ModelConfig[]>([])
const loading = ref(false)

const jobStatusFilter = ref('')
const selectedJobIds = ref(new Set<string>())
const batchDeleting = ref(false)

const newUsername = ref('')
const newPassword = ref('')
const newUserDisplayName = ref('')
const createUserError = ref('')
const createUserSuccess = ref('')

const editingUserId = ref<string | null>(null)
const editPassword = ref('')
const editDisplayName = ref('')
const editIsPublic = ref(false)
const editError = ref('')

// Provider state
const newProviderName = ref('')
const newProviderBaseUrl = ref('')
const newProviderApiKey = ref('')
const createProviderError = ref('')
const revealedKeys = ref(new Set<string>())
const editingProviderId = ref<string | null>(null)
const editProvider = ref<Partial<UpstreamProvider>>({})
const editProviderError = ref('')

// Model state
const newModelId = ref('')
const newModelLabel = ref('')
const newModelProviderId = ref('')
const newModelSupportsRef = ref(true)
const newModelCreditCost = ref(1)
const newModelSizes = ref('')
const createModelError = ref('')
const editingModelId = ref<string | null>(null)
const editModel = ref<Partial<ModelConfig>>({})
const editModelSizes = ref('')
const editModelError = ref('')

// Billing state
const codes = ref<RedemptionCodeItem[]>([])
const codesFilter = ref<'all' | 'unused' | 'used'>('all')
const genCodeCount = ref(10)
const genCodeCredits = ref(100)
const genCodePrefix = ref('EP')
const genCodeResult = ref<string[]>([])
const genCodeError = ref('')

const adjustUserId = ref('')
const adjustAmount = ref(0)
const adjustReason = ref('')
const adjustResult = ref('')
const adjustError = ref('')

const transactions = ref<(CreditTransactionItem & { id: string; user_id: string; username: string | null })[]>([])
const txnFilterUserId = ref('')

// Modal state
const selectedJob = ref<AdminJobItem | null>(null)
const showCreateProviderModal = ref(false)
const showCreateModelModal = ref(false)

function formatDuration(start: string | null, end: string | null): string {
  if (!start || !end) return '-'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatMeta(meta: Record<string, unknown> | null): string {
  if (!meta) return '-'
  return JSON.stringify(meta, null, 2)
}

async function handleVerify() {
  if (!secretKey.value) {
    verifyError.value = '请输入管理员密钥。'
    return
  }
  verifying.value = true
  verifyError.value = ''
  try {
    await adminVerify(secretKey.value)
    await loadData()
  } catch (e) {
    verifyError.value = e instanceof Error ? e.message : '验证失败。'
  } finally {
    verifying.value = false
  }
}

async function loadData() {
  loading.value = true
  try {
    const [j, u, p, m] = await Promise.all([adminFetchJobs(jobStatusFilter.value || undefined), adminFetchUsers(), adminFetchProviders(), adminFetchModels()])
    jobs.value = j
    users.value = u
    providers.value = p
    models.value = m
    selectedJobIds.value = new Set()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      adminLogout()
      verifyError.value = '管理员密钥已过期，请重新验证。'
    }
  } finally {
    loading.value = false
  }
}

async function reloadJobs() {
  try {
    jobs.value = await adminFetchJobs(jobStatusFilter.value || undefined)
    selectedJobIds.value = new Set()
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      adminLogout()
      verifyError.value = '管理员密钥已过期，请重新验证。'
    }
  }
}

async function handleDeleteJob(jobId: string) {
  if (!confirm('确定要删除这个任务吗？将同时删除关联的图片产物。')) return
  try {
    await adminDeleteJob(jobId)
    jobs.value = jobs.value.filter((j) => j.job_id !== jobId)
    selectedJobIds.value.delete(jobId)
  } catch (e) {
    alert(e instanceof Error ? e.message : '删除失败。')
  }
}

function toggleJobSelect(jobId: string) {
  const s = new Set(selectedJobIds.value)
  if (s.has(jobId)) s.delete(jobId)
  else s.add(jobId)
  selectedJobIds.value = s
}

function toggleSelectAll() {
  if (selectedJobIds.value.size === jobs.value.length) {
    selectedJobIds.value = new Set()
  } else {
    selectedJobIds.value = new Set(jobs.value.map((j) => j.job_id))
  }
}

async function handleBatchDelete() {
  if (selectedJobIds.value.size === 0) return
  const count = selectedJobIds.value.size
  if (!confirm(`确定要删除选中的 ${count} 个任务吗？将同时删除关联的图片产物。`)) return
  batchDeleting.value = true
  try {
    const result = await adminBatchDeleteJobs([...selectedJobIds.value])
    await reloadJobs()
    alert(`已删除 ${result.deleted} 个任务${result.failed.length > 0 ? `，${result.failed.length} 个失败` : ''}。`)
  } catch (e) {
    alert(e instanceof Error ? e.message : '批量删除失败。')
  } finally {
    batchDeleting.value = false
  }
}

async function handleCreateUser() {
  if (!newUsername.value || !newPassword.value) {
    createUserError.value = '请输入用户名和密码。'
    return
  }
  createUserError.value = ''
  createUserSuccess.value = ''
  try {
    const user = await adminCreateUser({
      username: newUsername.value,
      password: newPassword.value,
      display_name: newUserDisplayName.value || undefined,
    })
    users.value.push(user)
    createUserSuccess.value = `用户 ${user.username} 创建成功。`
    newUsername.value = ''
    newPassword.value = ''
    newUserDisplayName.value = ''
  } catch (e) {
    createUserError.value = e instanceof Error ? e.message : '创建失败。'
  }
}

function startEditUser(user: UserInfo) {
  editingUserId.value = user.id
  editPassword.value = ''
  editDisplayName.value = user.display_name
  editIsPublic.value = user.is_public
  editError.value = ''
}

function cancelEdit() {
  editingUserId.value = null
}

async function saveEditUser() {
  if (!editingUserId.value) return
  editError.value = ''
  try {
    const data: { password?: string; display_name?: string; is_public?: boolean } = {}
    if (editPassword.value) data.password = editPassword.value
    data.display_name = editDisplayName.value
    data.is_public = editIsPublic.value
    const updated = await adminUpdateUser(editingUserId.value, data)
    const idx = users.value.findIndex((u) => u.id === updated.id)
    if (idx >= 0) users.value.splice(idx, 1, updated)
    editingUserId.value = null
  } catch (e) {
    editError.value = e instanceof Error ? e.message : '保存失败。'
  }
}

async function handleDeleteUser(userId: string) {
  if (!confirm('确定要删除该用户吗？该用户的任务不会被自动删除。')) return
  try {
    await adminDeleteUser(userId)
    users.value = users.value.filter((u) => u.id !== userId)
  } catch (e) {
    alert(e instanceof Error ? e.message : '删除失败。')
  }
}

function handleLogout() {
  adminLogout()
  secretKey.value = ''
  jobs.value = []
  users.value = []
  providers.value = []
  models.value = []
}

// ---- Provider handlers ----

async function handleCreateProvider() {
  if (!newProviderName.value || !newProviderBaseUrl.value || !newProviderApiKey.value) {
    createProviderError.value = '请填写名称、地址和密钥。'
    return
  }
  createProviderError.value = ''
  try {
    const p = await adminCreateProvider({
      name: newProviderName.value,
      base_url: newProviderBaseUrl.value,
      api_key: newProviderApiKey.value,
    })
    providers.value.push(p)
    newProviderName.value = ''
    newProviderBaseUrl.value = ''
    newProviderApiKey.value = ''
    showCreateProviderModal.value = false
  } catch (e) {
    createProviderError.value = e instanceof Error ? e.message : '创建失败。'
  }
}

function startEditProvider(p: UpstreamProvider) {
  editingProviderId.value = p.id
  editProvider.value = { ...p }
  editProviderError.value = ''
}

function cancelEditProvider() {
  editingProviderId.value = null
}

async function saveEditProvider() {
  if (!editingProviderId.value || !editProvider.value) return
  editProviderError.value = ''
  try {
    const updated = await adminUpdateProvider(editingProviderId.value, editProvider.value)
    const idx = providers.value.findIndex((p) => p.id === updated.id)
    if (idx >= 0) providers.value.splice(idx, 1, updated)
    editingProviderId.value = null
  } catch (e) {
    editProviderError.value = e instanceof Error ? e.message : '保存失败。'
  }
}

async function handleDeleteProvider(providerId: string) {
  if (!confirm('确定要删除该上游吗？需要先删除或迁移其关联的模型。')) return
  try {
    await adminDeleteProvider(providerId)
    providers.value = providers.value.filter((p) => p.id !== providerId)
  } catch (e) {
    alert(e instanceof Error ? e.message : '删除失败。')
  }
}

// ---- Model handlers ----

async function handleCreateModel() {
  if (!newModelId.value || !newModelLabel.value || !newModelProviderId.value) {
    createModelError.value = '请填写模型 ID、名称和选择上游。'
    return
  }
  createModelError.value = ''
  const sizes = newModelSizes.value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  try {
    const m = await adminCreateModel({
      id: newModelId.value,
      provider_id: newModelProviderId.value,
      label: newModelLabel.value,
      supports_reference_image: newModelSupportsRef.value,
      supported_sizes: sizes,
      credit_cost: newModelCreditCost.value,
    })
    models.value.push(m)
    newModelId.value = ''
    newModelLabel.value = ''
    newModelSupportsRef.value = true
    newModelCreditCost.value = 1
    newModelSizes.value = ''
    showCreateModelModal.value = false
  } catch (e) {
    createModelError.value = e instanceof Error ? e.message : '创建失败。'
  }
}

function startEditModel(m: ModelConfig) {
  editingModelId.value = m.id
  editModel.value = { ...m }
  editModelSizes.value = m.supported_sizes.join(', ')
  editModelError.value = ''
}

function cancelEditModel() {
  editingModelId.value = null
  editModelSizes.value = ''
}

async function saveEditModel() {
  if (!editingModelId.value || !editModel.value) return
  editModelError.value = ''
  const sizes = editModelSizes.value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  try {
    const updated = await adminUpdateModel(editingModelId.value, {
      ...editModel.value,
      supported_sizes: sizes,
    })
    const idx = models.value.findIndex((m) => m.id === updated.id)
    if (idx >= 0) models.value.splice(idx, 1, updated)
    editingModelId.value = null
    editModelSizes.value = ''
  } catch (e) {
    editModelError.value = e instanceof Error ? e.message : '保存失败。'
  }
}

async function handleDeleteModel(modelId: string) {
  if (!confirm('确定要删除该模型吗？')) return
  try {
    await adminDeleteModel(modelId)
    models.value = models.value.filter((m) => m.id !== modelId)
  } catch (e) {
    alert(e instanceof Error ? e.message : '删除失败。')
  }
}

function getProviderName(providerId: string): string {
  return providers.value.find((p) => p.id === providerId)?.name ?? providerId
}

function maskKey(key: string): string {
  if (key.length <= 8) return '****'
  return key.slice(0, 3) + '****' + key.slice(-4)
}

function toggleKeyReveal(providerId: string) {
  const set = new Set(revealedKeys.value)
  if (set.has(providerId)) {
    set.delete(providerId)
  } else {
    set.add(providerId)
  }
  revealedKeys.value = set
}

// Billing functions
async function loadCodes() {
  try {
    codes.value = await adminFetchCodes(codesFilter.value)
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      adminLogout()
      verifyError.value = '管理员密钥已过期，请重新验证。'
    }
  }
}

async function handleGenerateCodes() {
  genCodeError.value = ''
  genCodeResult.value = []
  try {
    const result = await adminGenerateCodes({
      count: genCodeCount.value,
      credits: genCodeCredits.value,
      prefix: genCodePrefix.value || undefined,
    })
    genCodeResult.value = result.codes
    await loadCodes()
  } catch (e) {
    genCodeError.value = e instanceof Error ? e.message : '生成失败。'
  }
}

async function loadTransactions() {
  try {
    transactions.value = await adminFetchTransactions(txnFilterUserId.value || undefined)
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      adminLogout()
      verifyError.value = '管理员密钥已过期，请重新验证。'
    }
  }
}

async function handleAdjustCredits() {
  if (!adjustUserId.value) {
    adjustError.value = '请选择用户。'
    return
  }
  adjustError.value = ''
  adjustResult.value = ''
  try {
    const result = await adminAdjustCredits(adjustUserId.value, {
      amount: adjustAmount.value,
      reason: adjustReason.value || undefined,
    })
    adjustResult.value = `调整成功，当前余额 ${result.credits} 积分。`
    await loadData()
    await loadTransactions()
  } catch (e) {
    adjustError.value = e instanceof Error ? e.message : '调整失败。'
  }
}

function switchCodesFilter(filter: 'all' | 'unused' | 'used') {
  codesFilter.value = filter
  void loadCodes()
}

onMounted(() => {
  if (isAdmin()) {
    void loadData()
  }
})
</script>

<template>
  <div class="admin-page">
    <template v-if="!isAdmin()">
      <div class="auth-card">
        <h1 class="auth-title">管理后台</h1>
        <form class="auth-form" @submit.prevent="handleVerify">
          <label class="auth-label">
            管理员密钥
            <input v-model="secretKey" type="password" class="auth-input" />
          </label>
          <p v-if="verifyError" class="auth-error">{{ verifyError }}</p>
          <button type="submit" class="auth-submit" :disabled="verifying">
            {{ verifying ? '验证中…' : '验证' }}
          </button>
        </form>
      </div>
    </template>

    <template v-else>
      <div class="admin-layout">
        <!-- Top Bar -->
        <header class="admin-topbar">
          <button class="admin-hamburger" @click="sidebarOpen = !sidebarOpen">
            <Menu :size="20" />
          </button>
          <h1 class="admin-topbar-title">管理后台</h1>
          <button class="admin-logout-btn" @click="handleLogout">
            <LogOut :size="16" />
            <span>退出管理</span>
          </button>
        </header>

        <!-- Sidebar -->
        <aside class="admin-sidebar" :class="{ open: sidebarOpen }">
          <nav class="admin-nav">
            <button
              v-for="item in navItems"
              :key="item.key"
              :class="['admin-nav-item', { active: activeSection === item.key }]"
              @click="activeSection = item.key; sidebarOpen = false"
            >
              <component :is="item.icon" :size="18" />
              <span>{{ item.label }}</span>
            </button>
          </nav>
        </aside>

        <!-- Mobile Backdrop -->
        <div v-if="sidebarOpen" class="admin-sidebar-backdrop" @click="sidebarOpen = false" />

        <!-- Main Content -->
        <main class="admin-main">
          <div v-if="loading" class="loading-state">正在加载数据…</div>

          <!-- Upstream Providers -->
          <section v-show="activeSection === 'providers'" class="admin-section">
        <div class="admin-section-header">
          <h2 class="admin-section-title">上游管理</h2>
          <button class="admin-btn" @click="createProviderError = ''; showCreateProviderModal = true">新增上游</button>
        </div>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>名称</th><th>API 地址</th><th>API Key</th><th>超时</th><th>默认格式</th><th>操作</th></tr>
            </thead>
            <tbody>
              <template v-for="p in providers" :key="p.id">
                <tr v-if="editingProviderId !== p.id">
                  <td>{{ p.name }}</td>
                  <td class="td-url">{{ p.base_url }}</td>
                  <td class="td-key" @click="toggleKeyReveal(p.id)">
                    <span v-if="revealedKeys.has(p.id)" class="key-full">{{ p.api_key }}</span>
                    <span v-else class="key-masked">{{ maskKey(p.api_key) }}</span>
                  </td>
                  <td>{{ p.timeout_seconds }}s</td>
                  <td>{{ p.default_output_format }} / {{ p.default_quality }}</td>
                  <td class="td-actions">
                    <button class="admin-edit-btn" @click="startEditProvider(p)">编辑</button>
                    <button class="admin-delete-btn" @click="handleDeleteProvider(p.id)">删除</button>
                  </td>
                </tr>
                <tr v-else class="edit-row">
                  <td><input v-model="editProvider.name" class="admin-input-inline" /></td>
                  <td><input v-model="editProvider.base_url" class="admin-input-inline admin-input-wide" /></td>
                  <td><input v-model.number="editProvider.timeout_seconds" type="number" class="admin-input-inline" style="width:70px" /></td>
                  <td>
                    <select v-model="editProvider.default_output_format" class="admin-input-inline">
                      <option value="jpeg">JPEG</option>
                      <option value="png">PNG</option>
                      <option value="webp">WebP</option>
                    </select>
                    <select v-model="editProvider.default_quality" class="admin-input-inline" style="margin-left:4px">
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                      <option value="auto">Auto</option>
                    </select>
                  </td>
                  <td class="td-actions">
                    <input v-model="editProvider.api_key" type="password" placeholder="API 密钥" class="admin-input-inline admin-input-password" />
                    <button class="admin-save-btn" @click="saveEditProvider">保存</button>
                    <button class="admin-cancel-btn" @click="cancelEditProvider">取消</button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <p v-if="editProviderError" class="auth-error">{{ editProviderError }}</p>
      </section>

      <!-- Model Configs -->
      <section v-show="activeSection === 'models'" class="admin-section">
        <div class="admin-section-header">
          <h2 class="admin-section-title">模型管理</h2>
          <button class="admin-btn" @click="createModelError = ''; showCreateModelModal = true">新增模型</button>
        </div>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>ID</th><th>名称</th><th>上游</th><th>参考图</th><th>积分/张</th><th>启用</th><th>操作</th></tr>
            </thead>
            <tbody>
              <template v-for="m in models" :key="m.id">
                <tr v-if="editingModelId !== m.id">
                  <td class="td-id">{{ m.id }}</td>
                  <td>{{ m.label }}</td>
                  <td>{{ getProviderName(m.provider_id) }}</td>
                  <td>{{ m.supports_reference_image ? '是' : '否' }}</td>
                  <td>{{ m.credit_cost }}</td>
                  <td>{{ m.enabled ? '是' : '否' }}</td>
                  <td class="td-actions">
                    <button class="admin-edit-btn" @click="startEditModel(m)">编辑</button>
                    <button class="admin-delete-btn" @click="handleDeleteModel(m.id)">删除</button>
                  </td>
                </tr>
                <tr v-else class="edit-row">
                  <td class="td-id">{{ m.id }}</td>
                  <td><input v-model="editModel.label" class="admin-input-inline" /></td>
                  <td>
                    <select v-model="editModel.provider_id" class="admin-input-inline">
                      <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
                    </select>
                  </td>
                  <td><input v-model="editModel.supports_reference_image" type="checkbox" /></td>
                  <td><input v-model.number="editModel.credit_cost" type="number" min="1" class="admin-input-inline" style="width:60px" /></td>
                  <td><input v-model="editModel.enabled" type="checkbox" /></td>
                  <td class="td-actions">
                    <input v-model="editModelSizes" class="admin-input-inline admin-input-password" placeholder="尺寸(逗号分隔)" />
                    <button class="admin-save-btn" @click="saveEditModel">保存</button>
                    <button class="admin-cancel-btn" @click="cancelEditModel">取消</button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <p v-if="editModelError" class="auth-error">{{ editModelError }}</p>
      </section>

      <!-- Users -->
      <section v-show="activeSection === 'users'" class="admin-section">
        <h2 class="admin-section-title">新增用户</h2>
        <form class="admin-create-form" @submit.prevent="handleCreateUser">
          <input v-model="newUsername" type="text" placeholder="用户名" class="admin-input" maxlength="64" />
          <input v-model="newPassword" type="password" placeholder="密码" class="admin-input" maxlength="128" />
          <input v-model="newUserDisplayName" type="text" placeholder="显示名称（可选）" class="admin-input" maxlength="128" />
          <button type="submit" class="admin-btn">创建用户</button>
        </form>
        <p v-if="createUserError" class="auth-error">{{ createUserError }}</p>
        <p v-if="createUserSuccess" class="admin-success">{{ createUserSuccess }}</p>
      </section>

      <section v-show="activeSection === 'users'" class="admin-section">
        <h2 class="admin-section-title">用户列表</h2>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>用户名</th><th>显示名称</th><th>积分</th><th>公开画廊</th><th>注册时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <template v-for="user in users" :key="user.id">
                <tr v-if="editingUserId !== user.id">
                  <td>{{ user.username }}</td>
                  <td>{{ user.display_name }}</td>
                  <td>{{ user.credits ?? 0 }}</td>
                  <td>{{ user.is_public ? '是' : '否' }}</td>
                  <td>{{ new Date(user.created_at).toLocaleString() }}</td>
                  <td class="td-actions">
                    <button class="admin-edit-btn" @click="startEditUser(user)">编辑</button>
                    <button class="admin-delete-btn" @click="handleDeleteUser(user.id)">删除</button>
                  </td>
                </tr>
                <tr v-else class="edit-row">
                  <td>{{ user.username }}</td>
                  <td><input v-model="editDisplayName" class="admin-input-inline" maxlength="128" /></td>
                  <td>{{ user.credits ?? 0 }}</td>
                  <td><input v-model="editIsPublic" type="checkbox" /></td>
                  <td>{{ new Date(user.created_at).toLocaleString() }}</td>
                  <td class="td-actions">
                    <input v-model="editPassword" type="password" placeholder="新密码（留空不改）" class="admin-input-inline admin-input-password" />
                    <button class="admin-save-btn" @click="saveEditUser">保存</button>
                    <button class="admin-cancel-btn" @click="cancelEdit">取消</button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <p v-if="editError" class="auth-error">{{ editError }}</p>
      </section>

      <!-- Jobs -->
      <section v-show="activeSection === 'jobs'" class="admin-section">
        <div class="admin-section-header">
          <h2 class="admin-section-title">任务列表</h2>
          <div class="admin-job-toolbar">
            <select v-model="jobStatusFilter" class="admin-input" @change="reloadJobs">
              <option value="">全部状态</option>
              <option value="queued">排队中</option>
              <option value="processing">生成中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </select>
            <button
              v-if="selectedJobIds.size > 0"
              class="admin-delete-btn"
              :disabled="batchDeleting"
              @click="handleBatchDelete"
            >
              <Trash2 :size="14" style="margin-right:4px" />
              删除选中 ({{ selectedJobIds.size }})
            </button>
          </div>
        </div>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th style="width:36px"><input type="checkbox" :checked="selectedJobIds.size === jobs.length && jobs.length > 0" @change="toggleSelectAll" /></th>
                <th>ID</th><th>状态</th><th>提示词</th><th>模型</th><th>用户</th><th>耗时</th><th>创建时间</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="job in jobs" :key="job.job_id">
                <td><input type="checkbox" :checked="selectedJobIds.has(job.job_id)" @change="toggleJobSelect(job.job_id)" /></td>
                <td class="td-id">{{ job.job_id.slice(0, 8) }}</td>
                <td>
                  <span :class="['status-badge', `status-${job.status}`]">{{ job.status }}</span>
                </td>
                <td class="td-prompt">{{ job.prompt }}</td>
                <td>{{ job.model }}</td>
                <td>{{ job.username || '-' }}</td>
                <td class="td-duration">{{ formatDuration(job.started_at, job.finished_at) }}</td>
                <td>{{ new Date(job.created_at).toLocaleString() }}</td>
                <td class="td-actions">
                  <button class="admin-edit-btn" @click="selectedJob = job"><Eye :size="14" /></button>
                  <button class="admin-delete-btn" @click="handleDeleteJob(job.job_id)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Billing -->
      <section v-show="activeSection === 'billing'" class="admin-section">
        <div class="admin-section-header">
          <h2 class="admin-section-title"><Ticket :size="18" style="vertical-align:middle;margin-right:6px" />兑换码管理</h2>
          <div class="admin-billing-filters">
            <button :class="['admin-btn-sm', { active: codesFilter === 'all' }]" @click="switchCodesFilter('all')">全部</button>
            <button :class="['admin-btn-sm', { active: codesFilter === 'unused' }]" @click="switchCodesFilter('unused')">未使用</button>
            <button :class="['admin-btn-sm', { active: codesFilter === 'used' }]" @click="switchCodesFilter('used')">已使用</button>
          </div>
        </div>

        <form class="admin-create-form" @submit.prevent="handleGenerateCodes">
          <input v-model.number="genCodeCount" type="number" min="1" max="1000" class="admin-input" style="width:80px" placeholder="数量" />
          <input v-model.number="genCodeCredits" type="number" min="1" class="admin-input" style="width:100px" placeholder="面额" />
          <input v-model="genCodePrefix" type="text" class="admin-input" style="width:80px" maxlength="8" placeholder="前缀" />
          <button type="submit" class="admin-btn">批量生成</button>
        </form>
        <p v-if="genCodeError" class="auth-error">{{ genCodeError }}</p>
        <div v-if="genCodeResult.length > 0" class="admin-code-result">
          <p class="admin-success">已生成 {{ genCodeResult.length }} 个兑换码：</p>
          <textarea class="admin-code-textarea" :value="genCodeResult.join('\n')" readonly rows="6" />
        </div>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>兑换码</th><th>面额</th><th>状态</th><th>使用者</th><th>使用时间</th><th>创建时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in codes" :key="c.id">
                <td class="td-mono">{{ c.code }}</td>
                <td>{{ c.credits }}</td>
                <td><span :class="['status-badge', c.used_by ? 'status-used' : 'status-unused']">{{ c.used_by ? '已使用' : '未使用' }}</span></td>
                <td>{{ c.used_by ? c.used_by.slice(0, 8) : '-' }}</td>
                <td>{{ c.used_at ? new Date(c.used_at).toLocaleString() : '-' }}</td>
                <td>{{ new Date(c.created_at).toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-show="activeSection === 'billing'" class="admin-section">
        <h2 class="admin-section-title"><Wallet :size="18" style="vertical-align:middle;margin-right:6px" />用户积分调整</h2>
        <form class="admin-create-form" @submit.prevent="handleAdjustCredits">
          <select v-model="adjustUserId" class="admin-input">
            <option value="" disabled>选择用户</option>
            <option v-for="u in users" :key="u.id" :value="u.id">{{ u.username }} ({{ u.credits ?? 0 }} 积分)</option>
          </select>
          <input v-model.number="adjustAmount" type="number" class="admin-input" style="width:100px" placeholder="数量" />
          <input v-model="adjustReason" type="text" class="admin-input" maxlength="256" placeholder="原因（可选）" />
          <button type="submit" class="admin-btn">调整</button>
        </form>
        <p v-if="adjustError" class="auth-error">{{ adjustError }}</p>
        <p v-if="adjustResult" class="admin-success">{{ adjustResult }}</p>
      </section>

      <section v-show="activeSection === 'billing'" class="admin-section">
        <div class="admin-section-header">
          <h2 class="admin-section-title"><ArrowRightLeft :size="18" style="vertical-align:middle;margin-right:6px" />消费记录</h2>
          <div>
            <select v-model="txnFilterUserId" class="admin-input" style="margin-right:8px" @change="loadTransactions">
              <option value="">全部用户</option>
              <option v-for="u in users" :key="u.id" :value="u.id">{{ u.username }}</option>
            </select>
            <button class="admin-btn-sm" @click="loadTransactions">刷新</button>
          </div>
        </div>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>时间</th><th>用户</th><th>变动</th><th>余额</th><th>原因</th></tr>
            </thead>
            <tbody>
              <tr v-for="txn in transactions" :key="txn.id">
                <td>{{ new Date(txn.created_at).toLocaleString() }}</td>
                <td>{{ txn.username || txn.user_id.slice(0, 8) }}</td>
                <td :class="txn.amount > 0 ? 'txn-positive' : 'txn-negative'">{{ txn.amount > 0 ? '+' : '' }}{{ txn.amount }}</td>
                <td>{{ txn.balance_after }}</td>
                <td>{{ txn.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
        </main>
      </div>

      <!-- Job Detail Modal -->
      <div v-if="selectedJob" class="modal-backdrop" @click.self="selectedJob = null">
        <div class="modal-panel admin-modal-panel">
          <div class="modal-toolbar">
            <button class="icon-button" @click="selectedJob = null"><X :size="20" /></button>
          </div>
          <div class="admin-detail-grid">
            <div class="admin-detail-section">
              <h3 class="admin-detail-heading">基本信息</h3>
              <dl class="admin-detail-list">
                <dt>任务 ID</dt><dd class="dd-mono">{{ selectedJob.job_id }}</dd>
                <dt>状态</dt><dd><span :class="['status-badge', `status-${selectedJob.status}`]">{{ selectedJob.status }}</span></dd>
                <dt>模型</dt><dd>{{ selectedJob.model }}</dd>
                <dt>尺寸</dt><dd>{{ selectedJob.size }}</dd>
                <dt>宽高比</dt><dd>{{ selectedJob.aspect_ratio }}</dd>
                <dt>用户</dt><dd>{{ selectedJob.username || '-' }}</dd>
                <dt>参考图</dt><dd>{{ selectedJob.reference_image_filename || '-' }}</dd>
              </dl>
            </div>
            <div class="admin-detail-section">
              <h3 class="admin-detail-heading">时间信息</h3>
              <dl class="admin-detail-list">
                <dt>创建时间</dt><dd>{{ new Date(selectedJob.created_at).toLocaleString() }}</dd>
                <dt>开始时间</dt><dd>{{ selectedJob.started_at ? new Date(selectedJob.started_at).toLocaleString() : '-' }}</dd>
                <dt>完成时间</dt><dd>{{ selectedJob.finished_at ? new Date(selectedJob.finished_at).toLocaleString() : '-' }}</dd>
                <dt>耗时</dt><dd class="dd-highlight">{{ formatDuration(selectedJob.started_at, selectedJob.finished_at) }}</dd>
              </dl>
            </div>
          </div>
          <div class="admin-detail-section">
            <h3 class="admin-detail-heading">提示词</h3>
            <p class="admin-detail-text">{{ selectedJob.prompt }}</p>
          </div>
          <div v-if="selectedJob.revised_prompt" class="admin-detail-section">
            <h3 class="admin-detail-heading">修订提示词</h3>
            <p class="admin-detail-text">{{ selectedJob.revised_prompt }}</p>
          </div>
          <div v-if="selectedJob.error_message" class="admin-detail-section">
            <h3 class="admin-detail-heading">错误信息</h3>
            <p class="admin-detail-text admin-detail-error">{{ selectedJob.error_message }}</p>
          </div>
          <div v-if="selectedJob.provider_job_meta" class="admin-detail-section">
            <h3 class="admin-detail-heading">上游渠道元数据</h3>
            <pre class="admin-detail-meta">{{ formatMeta(selectedJob.provider_job_meta) }}</pre>
          </div>
          <div v-if="selectedJob.image_url" class="admin-detail-section">
            <h3 class="admin-detail-heading">生成结果</h3>
            <img :src="selectedJob.image_url" class="admin-detail-image" alt="生成图片" />
          </div>
        </div>
      </div>

      <!-- Create Provider Modal -->
      <div v-if="showCreateProviderModal" class="modal-backdrop" @click.self="showCreateProviderModal = false">
        <div class="modal-panel admin-modal-panel admin-modal-form">
          <div class="modal-toolbar">
            <h3 class="admin-modal-title">新增上游</h3>
            <button class="icon-button" @click="showCreateProviderModal = false"><X :size="20" /></button>
          </div>
          <form class="admin-modal-form-body" @submit.prevent="handleCreateProvider()">
            <label class="admin-form-label">
              名称
              <input v-model="newProviderName" type="text" class="admin-input" maxlength="128" placeholder="如 OpenAI Proxy" />
            </label>
            <label class="admin-form-label">
              API 地址
              <input v-model="newProviderBaseUrl" type="text" class="admin-input" maxlength="512" placeholder="https://api.example.com/v1" />
            </label>
            <label class="admin-form-label">
              API 密钥
              <input v-model="newProviderApiKey" type="password" class="admin-input" maxlength="512" placeholder="sk-..." />
            </label>
            <p v-if="createProviderError" class="auth-error">{{ createProviderError }}</p>
            <button type="submit" class="admin-btn admin-btn-block">创建</button>
          </form>
        </div>
      </div>

      <!-- Create Model Modal -->
      <div v-if="showCreateModelModal" class="modal-backdrop" @click.self="showCreateModelModal = false">
        <div class="modal-panel admin-modal-panel admin-modal-form">
          <div class="modal-toolbar">
            <h3 class="admin-modal-title">新增模型</h3>
            <button class="icon-button" @click="showCreateModelModal = false"><X :size="20" /></button>
          </div>
          <form class="admin-modal-form-body" @submit.prevent="handleCreateModel()">
            <label class="admin-form-label">
              模型 ID
              <input v-model="newModelId" type="text" class="admin-input" maxlength="128" placeholder="gpt-image-2-c" />
            </label>
            <label class="admin-form-label">
              显示名称
              <input v-model="newModelLabel" type="text" class="admin-input" maxlength="256" placeholder="GPT-Image-2 C" />
            </label>
            <label class="admin-form-label">
              上游
              <select v-model="newModelProviderId" class="admin-input">
                <option value="" disabled>选择上游</option>
                <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select>
            </label>
            <label class="admin-form-label admin-form-label-row">
              <input v-model="newModelSupportsRef" type="checkbox" />
              <span>支持参考图</span>
            </label>
            <label class="admin-form-label">
              积分/张
              <input v-model.number="newModelCreditCost" type="number" min="1" class="admin-input" placeholder="1" />
            </label>
            <label class="admin-form-label">
              支持尺寸（逗号分隔，留空不限制）
              <input v-model="newModelSizes" type="text" class="admin-input" placeholder="1024x1024, 1280x720" />
            </label>
            <p v-if="createModelError" class="auth-error">{{ createModelError }}</p>
            <button type="submit" class="admin-btn admin-btn-block">创建</button>
          </form>
        </div>
      </div>
    </template>
  </div>
</template>
