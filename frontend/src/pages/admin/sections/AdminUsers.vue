<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { RefreshCw, Search, UserPlus } from 'lucide-vue-next'

import {
  ApiError,
  adminCreateUser,
  adminDeleteUser,
  adminFetchUsers,
  adminFetchUserGroups,
  adminUpdateUser,
} from '@/lib/api'
import type { UserGroup, UserInfo } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()

const users = ref<UserInfo[]>([])
const loading = ref(false)
const creating = ref(false)
const saving = ref(false)
const searchQuery = ref('')
const groupFilter = ref<string | null>(null)
const groups = ref<UserGroup[]>([])

const createFormRef = ref<FormInst | null>(null)
const createForm = reactive({ username: '', email: '', password: '', display_name: '', group_code: null as string | null })
const createRules: FormRules = {
  username: { required: true, message: '请输入用户名', trigger: ['input', 'blur'] },
  password: { required: true, message: '请输入密码', trigger: ['input', 'blur'] },
}

const editModalOpen = ref(false)
const editFormRef = ref<FormInst | null>(null)
const editForm = reactive({ id: '', username: '', email: '', display_name: '', password: '', is_public: false, group_code: null as string | null })

const enabledGroupOptions = computed(() => groups.value.filter((group) => group.is_enabled).map((group) => ({ label: `${group.name}（${group.code}）`, value: group.code })))
const allGroupOptions = computed(() => groups.value.map((group) => ({ label: `${group.name}（${group.code}）${group.is_enabled ? '' : ' · 已停用'}`, value: group.code })))
const editGroupOptions = computed(() => groups.value
  .filter((group) => group.is_enabled || group.code === editForm.group_code)
  .map((group) => ({ label: `${group.name}（${group.code}）${group.is_enabled ? '' : ' · 当前组已停用'}`, value: group.code })))
const editRules: FormRules = {
  display_name: { required: true, message: '请输入显示名称', trigger: ['input', 'blur'] },
}

const filteredUsers = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return users.value.filter((user) => {
    const matchesGroup = !groupFilter.value || user.group?.code === groupFilter.value
    const matchesQuery = !query || (
    user.username.toLocaleLowerCase().includes(query) ||
    user.display_name.toLocaleLowerCase().includes(query) ||
    (user.email?.toLocaleLowerCase().includes(query) ?? false)
    )
    return matchesGroup && matchesQuery
  })
})

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) {
    message.error('管理员密钥已过期，请重新验证。')
    emit('auth-expired')
    return
  }
  message.error(error instanceof Error ? error.message : fallback)
}

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

async function loadUsers() {
  loading.value = true
  try {
    users.value = await adminFetchUsers()
  } catch (error) {
    handleError(error, '用户列表加载失败。')
  } finally {
    loading.value = false
  }
}

async function loadGroups() {
  try { groups.value = await adminFetchUserGroups() } catch (error) { handleError(error, '用户组加载失败。') }
}

async function createUser() {
  try {
    await createFormRef.value?.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    const created = await adminCreateUser({
      username: createForm.username,
      email: createForm.email || undefined,
      password: createForm.password,
      display_name: createForm.display_name || undefined,
      group_code: createForm.group_code || undefined,
    })
    users.value.push(created)
    createForm.username = ''
    createForm.email = ''
    createForm.password = ''
    createForm.display_name = ''
    createForm.group_code = null
    createFormRef.value?.restoreValidation()
    message.success(`用户 ${created.username} 已创建。`)
  } catch (error) {
    handleError(error, '用户创建失败。')
  } finally {
    creating.value = false
  }
}

function openEdit(user: UserInfo) {
  editForm.id = user.id
  editForm.username = user.username
  editForm.email = user.email || ''
  editForm.display_name = user.display_name
  editForm.password = ''
  editForm.is_public = user.is_public
  editForm.group_code = user.group?.code ?? null
  editFormRef.value?.restoreValidation()
  editModalOpen.value = true
}

async function saveUser() {
  try {
    await editFormRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const updated = await adminUpdateUser(editForm.id, {
      email: editForm.email || null,
      display_name: editForm.display_name,
      is_public: editForm.is_public,
      group_code: editForm.group_code || undefined,
      ...(editForm.password ? { password: editForm.password } : {}),
    })
    const index = users.value.findIndex((user) => user.id === updated.id)
    if (index >= 0) users.value.splice(index, 1, updated)
    editModalOpen.value = false
    message.success('用户资料已更新。')
  } catch (error) {
    handleError(error, '用户更新失败。')
  } finally {
    saving.value = false
  }
}

function deleteUser(user: UserInfo) {
  dialog.warning({
    title: '删除用户',
    content: `确定删除用户“${user.username}”吗？该用户的任务不会被自动删除。`,
    positiveText: '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      try {
        await adminDeleteUser(user.id)
        users.value = users.value.filter((item) => item.id !== user.id)
        message.success('用户已删除。')
      } catch (error) {
        handleError(error, '用户删除失败。')
      }
    },
  })
}

const columns: DataTableColumns<UserInfo> = [
  { title: '用户名', key: 'username', minWidth: 130 },
  { title: '邮箱', key: 'email', minWidth: 200, render: (row) => row.email || '-' },
  { title: '显示名称', key: 'display_name', minWidth: 150 },
  { title: '用户组', key: 'group', width: 120, render: (row) => row.group ? h(NTag, { size: 'small', bordered: false, type: 'info' }, { default: () => row.group?.name ?? row.group?.code }) : '-' },
  { title: '灵感丝线', key: 'credits', width: 100 },
  {
    title: '公开画廊', key: 'is_public', width: 100,
    render: (row) => h(NTag, { size: 'small', type: row.is_public ? 'success' : 'default', bordered: false }, { default: () => row.is_public ? '公开' : '私密' }),
  },
  { title: '注册时间', key: 'created_at', minWidth: 180, render: (row) => formatDate(row.created_at) },
  {
    title: '操作', key: 'actions', width: 150, fixed: 'right',
    render(row) {
      return h(NSpace, { size: 6, wrap: false }, { default: () => [
        h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => deleteUser(row) }, { default: () => '删除' }),
      ] })
    },
  },
]

onMounted(() => { void loadUsers(); void loadGroups() })
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Users</p>
        <h1>用户管理</h1>
        <span>创建账户、补录邮箱、重置密码并检索已有用户。</span>
      </div>
      <NButton :loading="loading" @click="loadUsers"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
    </header>

    <NCard size="small" title="新增用户" class="create-card">
      <NForm ref="createFormRef" :model="createForm" :rules="createRules" label-placement="top" class="create-user-form" @submit.prevent="createUser">
        <NFormItem label="用户名" path="username"><NInput v-model:value="createForm.username" maxlength="64" /></NFormItem>
        <NFormItem label="邮箱"><NInput v-model:value="createForm.email" maxlength="320" placeholder="可选" /></NFormItem>
        <NFormItem label="密码" path="password"><NInput v-model:value="createForm.password" type="password" show-password-on="click" autocomplete="new-password" maxlength="128" /></NFormItem>
        <NFormItem label="显示名称"><NInput v-model:value="createForm.display_name" maxlength="128" placeholder="可选" /></NFormItem>
        <NFormItem label="用户组"><NSelect v-model:value="createForm.group_code" clearable :options="enabledGroupOptions" placeholder="默认组" /></NFormItem>
        <NButton type="primary" :loading="creating" class="create-button" @click="createUser"><template #icon><UserPlus :size="16" /></template>创建用户</NButton>
      </NForm>
    </NCard>

    <div class="table-toolbar">
      <NInput v-model:value="searchQuery" clearable placeholder="搜索用户名、邮箱或显示名称" class="search-input">
        <template #prefix><Search :size="15" /></template>
      </NInput>
      <NSelect v-model:value="groupFilter" clearable :options="allGroupOptions" placeholder="全部用户组" class="group-filter" />
      <span>{{ filteredUsers.length }} / {{ users.length }} 位用户</span>
    </div>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && filteredUsers.length === 0" :description="searchQuery ? '没有匹配的用户' : '还没有用户'" class="section-empty" />
      <NDataTable v-else :columns="columns" :data="filteredUsers" :row-key="(row: UserInfo) => row.id" size="small" :single-line="false" :scroll-x="1200" />
    </NSpin>

    <NModal v-model:show="editModalOpen" preset="card" title="编辑用户" class="admin-form-modal" :mask-closable="!saving">
      <NForm ref="editFormRef" :model="editForm" :rules="editRules" label-placement="top">
        <NFormItem label="用户名"><NInput :value="editForm.username" disabled /></NFormItem>
        <NFormItem label="邮箱"><NInput v-model:value="editForm.email" maxlength="320" placeholder="留空则不绑定邮箱" /></NFormItem>
        <NFormItem label="显示名称" path="display_name"><NInput v-model:value="editForm.display_name" maxlength="128" /></NFormItem>
        <NFormItem label="用户组"><NSelect v-model:value="editForm.group_code" :options="editGroupOptions" placeholder="请选择启用的用户组" /><small class="form-hint">更改只影响后续任务与参考图上传；停用组的现有成员可保留原组。</small></NFormItem>
        <NFormItem label="重置密码"><NInput v-model:value="editForm.password" type="password" show-password-on="click" autocomplete="new-password" maxlength="128" placeholder="超管可直接设置，留空则不修改" /></NFormItem>
        <NFormItem label="公开画廊"><NSwitch v-model:value="editForm.is_public" /></NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="saving" @click="editModalOpen = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="saveUser">保存</NButton>
        </NSpace>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.create-card { margin-bottom: 20px; }
.create-user-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)) auto; gap: 0 12px; align-items: end; }
.create-button { margin-bottom: 24px; }
.table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; color: var(--text-muted); font-size: 12px; }
.search-input { width: min(360px, 100%); }
.group-filter { width: 180px; }
.form-hint { display: block; margin-top: 6px; color: var(--text-muted); font-size: 12px; }
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
@media (max-width: 900px) { .create-user-form { grid-template-columns: repeat(2, minmax(0, 1fr)); } .create-button { align-self: center; } }
@media (max-width: 620px) { .create-user-form { grid-template-columns: 1fr; } .create-button { margin-bottom: 10px; } .table-toolbar { align-items: flex-start; flex-direction: column; } }
</style>
