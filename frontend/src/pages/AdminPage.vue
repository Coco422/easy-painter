<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adminCreateUser, adminDeleteJob, adminDeleteUser, adminFetchJobs, adminFetchUsers, adminUpdateUser } from '@/lib/api'
import { adminLogout, adminVerify, isAdmin } from '@/lib/auth'
import type { AdminJobItem, UserInfo } from '@/lib/types'

const secretKey = ref('')
const verifyError = ref('')
const verifying = ref(false)

const jobs = ref<AdminJobItem[]>([])
const users = ref<UserInfo[]>([])
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
    const [j, u] = await Promise.all([adminFetchJobs(), adminFetchUsers()])
    jobs.value = j
    users.value = u
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
