<script setup lang="ts">
import { h, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
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
import { Megaphone, Plus, RefreshCw, WandSparkles } from 'lucide-vue-next'

import {
  ApiError,
  adminCreateAnnouncement,
  adminDeleteAnnouncement,
  adminFetchAnnouncements,
  adminUpdateAnnouncement,
} from '@/lib/api'
import type { AnnouncementAudience, AnnouncementItem, AnnouncementLevel } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()

const announcements = ref<AnnouncementItem[]>([])
const loading = ref(false)
const creating = ref(false)
const saving = ref(false)
const changingId = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const pageSizes = [25, 50, 100]

const levelOptions = [
  { label: '普通', value: 'info' },
  { label: '提醒', value: 'warning' },
  { label: '重要', value: 'critical' },
]
const audienceOptions = [
  { label: '所有访客', value: 'all' },
  { label: '已登录用户', value: 'authenticated' },
  { label: '未绑定邮箱用户', value: 'unbound_email' },
]

const createFormRef = ref<FormInst | null>(null)
const createForm = reactive({
  title: '',
  content: '',
  level: 'warning' as AnnouncementLevel,
  audience: 'unbound_email' as AnnouncementAudience,
  enabled: true,
})
const formRules: FormRules = {
  title: { required: true, message: '请输入通知标题', trigger: ['input', 'blur'] },
  content: { required: true, message: '请输入通知内容', trigger: ['input', 'blur'] },
}

const editModalOpen = ref(false)
const editFormRef = ref<FormInst | null>(null)
const editForm = reactive({
  id: '',
  title: '',
  content: '',
  level: 'info' as AnnouncementLevel,
  audience: 'all' as AnnouncementAudience,
  enabled: true,
})

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) {
    message.error('管理员密钥已过期，请重新验证。')
    emit('auth-expired')
    return
  }
  message.error(error instanceof Error ? error.message : fallback)
}

function levelLabel(level: AnnouncementLevel) {
  return levelOptions.find((item) => item.value === level)?.label ?? level
}

function audienceLabel(audience: AnnouncementAudience) {
  return audienceOptions.find((item) => item.value === audience)?.label ?? audience
}

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

async function loadAnnouncements() {
  loading.value = true
  try {
    const response = await adminFetchAnnouncements(page.value, pageSize.value)
    announcements.value = response.items
    total.value = response.total
  } catch (error) {
    handleError(error, '通知列表加载失败。')
  } finally {
    loading.value = false
  }
}

function fillEmailReminder() {
  createForm.title = '邮箱绑定提醒'
  createForm.content = '未绑定邮箱的使用者请尽快前往个人中心绑定并验证邮箱，以便后续使用密码找回等功能。'
  createForm.level = 'warning'
  createForm.audience = 'unbound_email'
  createForm.enabled = true
}

async function createAnnouncement() {
  try {
    await createFormRef.value?.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    await adminCreateAnnouncement({ ...createForm })
    page.value = 1
    await loadAnnouncements()
    createForm.title = ''
    createForm.content = ''
    createFormRef.value?.restoreValidation()
    message.success('通知已创建并保存。')
  } catch (error) {
    handleError(error, '通知创建失败。')
  } finally {
    creating.value = false
  }
}

function changePage(nextPage: number) {
  page.value = nextPage
  void loadAnnouncements()
}

function changePageSize(nextPageSize: number) {
  pageSize.value = nextPageSize
  page.value = 1
  void loadAnnouncements()
}

function openEdit(row: AnnouncementItem) {
  Object.assign(editForm, row)
  editFormRef.value?.restoreValidation()
  editModalOpen.value = true
}

async function saveAnnouncement() {
  try {
    await editFormRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const updated = await adminUpdateAnnouncement(editForm.id, {
      title: editForm.title,
      content: editForm.content,
      level: editForm.level,
      audience: editForm.audience,
      enabled: editForm.enabled,
    })
    const index = announcements.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) announcements.value.splice(index, 1, updated)
    editModalOpen.value = false
    message.success('通知已更新。')
  } catch (error) {
    handleError(error, '通知更新失败。')
  } finally {
    saving.value = false
  }
}

async function toggleAnnouncement(row: AnnouncementItem) {
  changingId.value = row.id
  try {
    const updated = await adminUpdateAnnouncement(row.id, { enabled: !row.enabled })
    const index = announcements.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) announcements.value.splice(index, 1, updated)
    message.success(updated.enabled ? '通知已启用。' : '通知已停用。')
  } catch (error) {
    handleError(error, '通知状态更新失败。')
  } finally {
    changingId.value = ''
  }
}

function deleteAnnouncement(row: AnnouncementItem) {
  dialog.warning({
    title: '删除通知',
    content: `确定删除“${row.title}”吗？`,
    positiveText: '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      try {
        await adminDeleteAnnouncement(row.id)
        await loadAnnouncements()
        if (announcements.value.length === 0 && page.value > 1) {
          page.value -= 1
          await loadAnnouncements()
        }
        message.success('通知已删除。')
      } catch (error) {
        handleError(error, '通知删除失败。')
      }
    },
  })
}

const columns: DataTableColumns<AnnouncementItem> = [
  { title: '标题', key: 'title', minWidth: 150 },
  { title: '内容', key: 'content', minWidth: 300, ellipsis: { tooltip: true } },
  {
    title: '级别', key: 'level', width: 90,
    render: (row) => h(NTag, {
      size: 'small',
      type: row.level === 'critical' ? 'error' : row.level === 'warning' ? 'warning' : 'info',
      bordered: false,
    }, { default: () => levelLabel(row.level) }),
  },
  { title: '受众', key: 'audience', minWidth: 140, render: (row) => audienceLabel(row.audience) },
  {
    title: '状态', key: 'enabled', width: 90,
    render: (row) => h(NTag, { size: 'small', type: row.enabled ? 'success' : 'default', bordered: false }, { default: () => row.enabled ? '启用' : '停用' }),
  },
  { title: '更新时间', key: 'updated_at', minWidth: 180, render: (row) => formatDate(row.updated_at) },
  {
    title: '操作', key: 'actions', width: 210, fixed: 'right',
    render: (row) => h(NSpace, { size: 6, wrap: false }, { default: () => [
      h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => '编辑' }),
      h(NButton, { size: 'tiny', loading: changingId.value === row.id, onClick: () => toggleAnnouncement(row) }, { default: () => row.enabled ? '停用' : '启用' }),
      h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => deleteAnnouncement(row) }, { default: () => '删除' }),
    ] }),
  },
]

onMounted(loadAnnouncements)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Announcements</p>
        <h1>通知管理</h1>
        <span>维护多条系统横幅，并按登录状态或邮箱绑定状态定向投放。</span>
      </div>
      <NButton :loading="loading" @click="loadAnnouncements"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
    </header>

    <NCard size="small" class="announcement-create-card">
      <template #header><span class="card-title"><Megaphone :size="17" />新增通知</span></template>
      <template #header-extra>
        <NButton size="small" @click="fillEmailReminder"><template #icon><WandSparkles :size="14" /></template>填入邮箱提醒</NButton>
      </template>
      <NForm ref="createFormRef" :model="createForm" :rules="formRules" label-placement="top" @submit.prevent="createAnnouncement">
        <div class="announcement-form-grid">
          <NFormItem label="标题" path="title"><NInput v-model:value="createForm.title" maxlength="128" /></NFormItem>
          <NFormItem label="级别"><NSelect v-model:value="createForm.level" :options="levelOptions" /></NFormItem>
          <NFormItem label="受众"><NSelect v-model:value="createForm.audience" :options="audienceOptions" /></NFormItem>
          <NFormItem label="启用"><NSwitch v-model:value="createForm.enabled" /></NFormItem>
        </div>
        <NFormItem label="通知内容" path="content"><NInput v-model:value="createForm.content" type="textarea" maxlength="2000" show-count :autosize="{ minRows: 2, maxRows: 5 }" /></NFormItem>
        <NButton type="primary" :loading="creating" @click="createAnnouncement"><template #icon><Plus :size="15" /></template>创建通知</NButton>
      </NForm>
    </NCard>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && announcements.length === 0" description="还没有系统通知" class="section-empty" />
      <NDataTable v-else :columns="columns" :data="announcements" :row-key="(row: AnnouncementItem) => row.id" size="small" :single-line="false" :scroll-x="1180" :max-height="680" virtual-scroll />
    </NSpin>
    <div v-if="total > 0" class="table-pagination">
      <span>共 {{ total }} 条通知</span>
      <NPagination :page="page" :page-size="pageSize" :item-count="total" :page-sizes="pageSizes" show-size-picker @update:page="changePage" @update:page-size="changePageSize" />
    </div>

    <NModal v-model:show="editModalOpen" preset="card" title="编辑通知" class="admin-form-modal" :mask-closable="!saving">
      <NForm ref="editFormRef" :model="editForm" :rules="formRules" label-placement="top">
        <NFormItem label="标题" path="title"><NInput v-model:value="editForm.title" maxlength="128" /></NFormItem>
        <NFormItem label="通知内容" path="content"><NInput v-model:value="editForm.content" type="textarea" maxlength="2000" show-count :autosize="{ minRows: 3, maxRows: 8 }" /></NFormItem>
        <div class="edit-form-grid">
          <NFormItem label="级别"><NSelect v-model:value="editForm.level" :options="levelOptions" /></NFormItem>
          <NFormItem label="受众"><NSelect v-model:value="editForm.audience" :options="audienceOptions" /></NFormItem>
        </div>
        <NFormItem label="启用"><NSwitch v-model:value="editForm.enabled" /></NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="saving" @click="editModalOpen = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="saveAnnouncement">保存</NButton>
        </NSpace>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.announcement-create-card { margin-bottom: 20px; }
.card-title { display: inline-flex; align-items: center; gap: 8px; }
.announcement-form-grid { display: grid; grid-template-columns: minmax(220px, 1fr) 140px 190px 80px; gap: 0 12px; align-items: start; }
.edit-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.table-pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 14px; color: var(--text-muted); font-size: 12px; }
@media (max-width: 900px) { .announcement-form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .announcement-form-grid, .edit-form-grid { grid-template-columns: 1fr; } }
</style>
