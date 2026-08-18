<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  NAlert,
  NButton,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPagination,
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
const changingGroupUserIds = ref<Set<string>>(new Set())
const searchQuery = ref('')
const groupFilter = ref<string | null>(null)
const groups = ref<UserGroup[]>([])
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const pageSizes = [25, 50, 100]
let searchTimer: ReturnType<typeof setTimeout> | undefined

const createFormRef = ref<FormInst | null>(null)
const createModalOpen = ref(false)
const createForm = reactive({ username: '', email: '', password: '', display_name: '', group_code: null as string | null })
const createRules: FormRules = {
  username: { required: true, message: '请输入用户名', trigger: ['input', 'blur'] },
  password: { required: true, message: '请输入密码', trigger: ['input', 'blur'] },
}

const editModalOpen = ref(false)
const editFormRef = ref<FormInst | null>(null)
const editForm = reactive({ id: '', username: '', email: '', display_name: '', password: '', is_public: false, group_code: null as string | null })

const enabledGroupOptions = computed(() => groups.value
  .filter((group) => group.is_enabled)
  .map((group) => ({
    label: `${group.name}（${group.code}）${group.is_default ? ' · 默认' : ''}`,
    value: group.code,
  })))
const allGroupOptions = computed(() => groups.value.map((group) => ({
  label: `${group.name}（${group.code}）${group.is_default ? ' · 默认' : ''}${group.is_enabled ? '' : ' · 已停用'}`,
  value: group.code,
})))
const editGroupOptions = computed(() => groups.value
  .filter((group) => group.is_enabled || group.code === editForm.group_code)
  .map((group) => ({ label: `${group.name}（${group.code}）${group.is_enabled ? '' : ' · 当前组已停用'}`, value: group.code })))
const editRules: FormRules = {
  display_name: { required: true, message: '请输入显示名称', trigger: ['input', 'blur'] },
}

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
    const response = await adminFetchUsers({
      page: page.value,
      pageSize: pageSize.value,
      q: searchQuery.value.trim() || undefined,
      groupCode: groupFilter.value || undefined,
    })
    users.value = response.items
    total.value = response.total
  } catch (error) {
    handleError(error, '用户列表加载失败。')
  } finally {
    loading.value = false
  }
}

function changePage(nextPage: number) {
  page.value = nextPage
  void loadUsers()
}

function changePageSize(nextPageSize: number) {
  pageSize.value = nextPageSize
  page.value = 1
  void loadUsers()
}

function applyFilters() {
  page.value = 1
  void loadUsers()
}

function scheduleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(applyFilters, 300)
}

async function loadGroups() {
  try { groups.value = await adminFetchUserGroups() } catch (error) { handleError(error, '用户组加载失败。') }
}

async function refreshData() {
  await Promise.all([loadUsers(), loadGroups()])
}

function resetCreateForm() {
  createForm.username = ''
  createForm.email = ''
  createForm.password = ''
  createForm.display_name = ''
  createForm.group_code = groups.value.find((group) => group.is_default && group.is_enabled)?.code
    ?? groups.value.find((group) => group.is_enabled)?.code
    ?? null
}

function openCreate() {
  resetCreateForm()
  createFormRef.value?.restoreValidation()
  createModalOpen.value = true
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
    page.value = 1
    await loadUsers()
    createModalOpen.value = false
    resetCreateForm()
    createFormRef.value?.restoreValidation()
    message.success(`用户 ${created.username} 已创建。`)
  } catch (error) {
    handleError(error, '用户创建失败。')
  } finally {
    creating.value = false
  }
}

function groupOptionsFor(user: UserInfo) {
  return groups.value
    .filter((group) => group.is_enabled || group.code === user.group?.code)
    .map((group) => ({
      label: `${group.name}${group.is_default ? ' · 默认' : ''}${group.is_enabled ? '' : ' · 已停用'}`,
      value: group.code,
      disabled: !group.is_enabled,
    }))
}

function setChangingGroup(userId: string, changing: boolean) {
  const next = new Set(changingGroupUserIds.value)
  if (changing) next.add(userId)
  else next.delete(userId)
  changingGroupUserIds.value = next
}

function changeUserGroup(user: UserInfo, groupCode: string) {
  if (!groupCode || groupCode === user.group?.code) return
  const target = groups.value.find((group) => group.code === groupCode && group.is_enabled)
  if (!target) {
    message.error('目标用户组不存在或已停用。')
    return
  }
  dialog.warning({
    title: '更改用户组',
    content: `将“${user.username}”从“${user.group?.name ?? '未分组'}”调整为“${target.name}”？该变更只影响后续任务和上传，历史价格与到期时间不追溯。`,
    positiveText: '确认更改',
    negativeText: '取消',
    async onPositiveClick() {
      setChangingGroup(user.id, true)
      try {
        const updated = await adminUpdateUser(user.id, { group_code: groupCode })
        const index = users.value.findIndex((item) => item.id === updated.id)
        if (index >= 0) users.value.splice(index, 1, updated)
        if (groupFilter.value && updated.group?.code !== groupFilter.value) await loadUsers()
        message.success(`${user.username} 已切换到 ${updated.group?.name ?? target.name}。`)
      } catch (error) {
        handleError(error, '用户组更新失败。')
      } finally {
        setChangingGroup(user.id, false)
      }
    },
  })
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
        await loadUsers()
        if (users.value.length === 0 && page.value > 1) {
          page.value -= 1
          await loadUsers()
        }
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
  {
    title: '用户组', key: 'group', width: 170,
    render: (row) => h(NSelect, {
      value: row.group?.code ?? null,
      options: groupOptionsFor(row),
      size: 'small',
      loading: changingGroupUserIds.value.has(row.id),
      disabled: groups.value.length === 0 || changingGroupUserIds.value.has(row.id),
      placeholder: '选择用户组',
      consistentMenuWidth: false,
      'aria-label': `更改 ${row.username} 的用户组`,
      'onUpdate:value': (value: string) => changeUserGroup(row, value),
    }),
  },
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

onMounted(() => { void refreshData() })
onBeforeUnmount(() => { if (searchTimer) clearTimeout(searchTimer) })
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Users</p>
        <h1>用户管理</h1>
        <span>检索用户、快捷调整分组，并集中维护账户资料。</span>
      </div>
      <NSpace>
        <NButton :loading="loading" @click="refreshData"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
        <NButton type="primary" :disabled="groups.length === 0" @click="openCreate"><template #icon><UserPlus :size="16" /></template>创建用户</NButton>
      </NSpace>
    </header>

    <div class="table-toolbar">
      <NInput v-model:value="searchQuery" clearable placeholder="搜索用户名、邮箱或显示名称" class="search-input" @update:value="scheduleSearch">
        <template #prefix><Search :size="15" /></template>
      </NInput>
      <NSelect v-model:value="groupFilter" clearable :options="allGroupOptions" placeholder="全部用户组" class="group-filter" @update:value="applyFilters" />
      <span>共 {{ total }} 位用户</span>
    </div>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && users.length === 0" :description="searchQuery ? '没有匹配的用户' : '还没有用户'" class="section-empty" />
      <NDataTable v-else :columns="columns" :data="users" :row-key="(row: UserInfo) => row.id" size="small" :single-line="false" :scroll-x="1200" :max-height="680" virtual-scroll />
    </NSpin>

    <div v-if="total > 0" class="table-pagination">
      <span>第 {{ page }} 页</span>
      <NPagination :page="page" :page-size="pageSize" :item-count="total" :page-sizes="pageSizes" show-size-picker @update:page="changePage" @update:page-size="changePageSize" />
    </div>

    <NModal v-model:show="createModalOpen" preset="card" title="创建用户" class="admin-form-modal" :mask-closable="!creating" :close-on-esc="!creating">
      <NForm ref="createFormRef" :model="createForm" :rules="createRules" label-placement="top" @submit.prevent="createUser">
        <div class="user-form-grid">
          <NFormItem label="用户名" path="username"><NInput v-model:value="createForm.username" maxlength="64" placeholder="登录用户名" /></NFormItem>
          <NFormItem label="显示名称"><NInput v-model:value="createForm.display_name" maxlength="128" placeholder="可选，默认使用用户名" /></NFormItem>
          <NFormItem label="邮箱"><NInput v-model:value="createForm.email" maxlength="320" placeholder="可选" /></NFormItem>
          <NFormItem label="密码" path="password"><NInput v-model:value="createForm.password" type="password" show-password-on="click" autocomplete="new-password" maxlength="128" placeholder="设置初始密码" /></NFormItem>
        </div>
        <NFormItem label="用户组">
          <NSelect v-model:value="createForm.group_code" :options="enabledGroupOptions" placeholder="请选择用户组" />
        </NFormItem>
        <NAlert type="info" :bordered="false" title="分组策略">
          新用户默认使用当前默认组；分组决定后续生成结算倍率、媒体保留期和参考图上限。
        </NAlert>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="creating" @click="createModalOpen = false">取消</NButton>
          <NButton type="primary" :loading="creating" @click="createUser"><template #icon><UserPlus :size="16" /></template>创建用户</NButton>
        </NSpace>
      </template>
    </NModal>

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
.table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; color: var(--text-muted); font-size: 12px; }
.search-input { width: min(360px, 100%); }
.group-filter { width: 180px; }
.user-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.form-hint { display: block; margin-top: 6px; color: var(--text-muted); font-size: 12px; }
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.table-pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 14px; color: var(--text-muted); font-size: 12px; }
@media (max-width: 620px) { .user-form-grid { grid-template-columns: 1fr; } .table-toolbar { align-items: flex-start; flex-direction: column; } }
</style>
