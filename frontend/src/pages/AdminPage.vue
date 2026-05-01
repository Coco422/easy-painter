<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  adminCreateModel,
  adminCreateProvider,
  adminCreateUser,
  adminDeleteJob,
  adminDeleteModel,
  adminDeleteProvider,
  adminDeleteUser,
  adminFetchJobs,
  adminFetchModels,
  adminFetchProviders,
  adminFetchUsers,
  adminUpdateModel,
  adminUpdateProvider,
  adminUpdateUser,
} from '@/lib/api'
import { adminLogout, adminVerify, isAdmin } from '@/lib/auth'
import type { AdminJobItem, ModelConfig, UpstreamProvider, UserInfo } from '@/lib/types'

const secretKey = ref('')
const verifyError = ref('')
const verifying = ref(false)

const jobs = ref<AdminJobItem[]>([])
const users = ref<UserInfo[]>([])
const providers = ref<UpstreamProvider[]>([])
const models = ref<ModelConfig[]>([])
const loading = ref(false)

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
const createProviderSuccess = ref('')
const editingProviderId = ref<string | null>(null)
const editProvider = ref<Partial<UpstreamProvider>>({})
const editProviderError = ref('')

// Model state
const newModelId = ref('')
const newModelLabel = ref('')
const newModelProviderId = ref('')
const newModelSupportsRef = ref(true)
const newModelSizes = ref('')
const createModelError = ref('')
const createModelSuccess = ref('')
const editingModelId = ref<string | null>(null)
const editModel = ref<Partial<ModelConfig>>({})
const editModelSizes = ref('')
const editModelError = ref('')

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
    const [j, u, p, m] = await Promise.all([adminFetchJobs(), adminFetchUsers(), adminFetchProviders(), adminFetchModels()])
    jobs.value = j
    users.value = u
    providers.value = p
    models.value = m
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

async function handleDeleteJob(jobId: string) {
  if (!confirm('确定要删除这个任务吗？')) return
  try {
    await adminDeleteJob(jobId)
    jobs.value = jobs.value.filter((j) => j.job_id !== jobId)
  } catch (e) {
    alert(e instanceof Error ? e.message : '删除失败。')
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
  createProviderSuccess.value = ''
  try {
    const p = await adminCreateProvider({
      name: newProviderName.value,
      base_url: newProviderBaseUrl.value,
      api_key: newProviderApiKey.value,
    })
    providers.value.push(p)
    createProviderSuccess.value = `上游 "${p.name}" 创建成功。`
    newProviderName.value = ''
    newProviderBaseUrl.value = ''
    newProviderApiKey.value = ''
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
  createModelSuccess.value = ''
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
    })
    models.value.push(m)
    createModelSuccess.value = `模型 "${m.label}" 创建成功。`
    newModelId.value = ''
    newModelLabel.value = ''
    newModelSupportsRef.value = true
    newModelSizes.value = ''
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
      <div class="admin-header">
        <h1 class="admin-title">管理后台</h1>
        <button class="admin-logout-btn" @click="handleLogout">退出管理</button>
      </div>

      <div v-if="loading" class="loading-state">正在加载数据…</div>

      <!-- Upstream Providers -->
      <section class="admin-section">
        <h2 class="admin-section-title">上游管理</h2>
        <form class="admin-create-form" @submit.prevent="handleCreateProvider">
          <input v-model="newProviderName" type="text" placeholder="名称" class="admin-input" maxlength="128" />
          <input v-model="newProviderBaseUrl" type="text" placeholder="API 地址" class="admin-input admin-input-wide" maxlength="512" />
          <input v-model="newProviderApiKey" type="password" placeholder="API 密钥" class="admin-input admin-input-wide" maxlength="512" />
          <button type="submit" class="admin-btn">新增上游</button>
        </form>
        <p v-if="createProviderError" class="auth-error">{{ createProviderError }}</p>
        <p v-if="createProviderSuccess" class="admin-success">{{ createProviderSuccess }}</p>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>名称</th><th>API 地址</th><th>超时</th><th>默认格式</th><th>操作</th></tr>
            </thead>
            <tbody>
              <template v-for="p in providers" :key="p.id">
                <tr v-if="editingProviderId !== p.id">
                  <td>{{ p.name }}</td>
                  <td class="td-url">{{ p.base_url }}</td>
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
      <section class="admin-section">
        <h2 class="admin-section-title">模型管理</h2>
        <form class="admin-create-form" @submit.prevent="handleCreateModel">
          <input v-model="newModelId" type="text" placeholder="模型 ID" class="admin-input" maxlength="128" />
          <input v-model="newModelLabel" type="text" placeholder="显示名称" class="admin-input" maxlength="256" />
          <select v-model="newModelProviderId" class="admin-input">
            <option value="" disabled>选择上游</option>
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <label class="admin-checkbox-label">
            <input v-model="newModelSupportsRef" type="checkbox" />
            支持参考图
          </label>
          <input v-model="newModelSizes" type="text" placeholder="支持尺寸(逗号分隔)" class="admin-input admin-input-wide" />
          <button type="submit" class="admin-btn">新增模型</button>
        </form>
        <p v-if="createModelError" class="auth-error">{{ createModelError }}</p>
        <p v-if="createModelSuccess" class="admin-success">{{ createModelSuccess }}</p>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>ID</th><th>名称</th><th>上游</th><th>参考图</th><th>启用</th><th>操作</th></tr>
            </thead>
            <tbody>
              <template v-for="m in models" :key="m.id">
                <tr v-if="editingModelId !== m.id">
                  <td class="td-id">{{ m.id }}</td>
                  <td>{{ m.label }}</td>
                  <td>{{ getProviderName(m.provider_id) }}</td>
                  <td>{{ m.supports_reference_image ? '是' : '否' }}</td>
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
      <section class="admin-section">
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

      <section class="admin-section">
        <h2 class="admin-section-title">用户列表</h2>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>用户名</th><th>显示名称</th><th>公开画廊</th><th>注册时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <template v-for="user in users" :key="user.id">
                <tr v-if="editingUserId !== user.id">
                  <td>{{ user.username }}</td>
                  <td>{{ user.display_name }}</td>
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
      <section class="admin-section">
        <h2 class="admin-section-title">任务列表</h2>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr><th>ID</th><th>状态</th><th>提示词</th><th>模型</th><th>用户</th><th>创建时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="job in jobs" :key="job.job_id">
                <td class="td-id">{{ job.job_id.slice(0, 8) }}</td>
                <td>{{ job.status }}</td>
                <td class="td-prompt">{{ job.prompt }}</td>
                <td>{{ job.model }}</td>
                <td>{{ job.username || '-' }}</td>
                <td>{{ new Date(job.created_at).toLocaleString() }}</td>
                <td>
                  <button class="admin-delete-btn" @click="handleDeleteJob(job.job_id)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
