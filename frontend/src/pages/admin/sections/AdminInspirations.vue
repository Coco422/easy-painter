<script setup lang="ts">
import { h, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSpace,
  NSpin,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { Check, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'

import {
  ApiError,
  adminCreateInspiration,
  adminCreateInspirationFromJob,
  adminDeleteInspiration,
  adminFetchInspirationCandidates,
  adminFetchInspirations,
  adminUpdateInspiration,
} from '@/lib/api'
import type { AdminInspirationCandidate, AdminInspirationItem } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const candidates = ref<AdminInspirationCandidate[]>([])
const inspirations = ref<AdminInspirationItem[]>([])
const collectingId = ref('')

const importOpen = ref(false)
const importing = ref(false)
const importFile = ref<File | null>(null)
const importForm = reactive({
  title: '',
  prompt: '',
  description: '',
  source: 'admin-imported',
  source_url: '',
  author_name: '',
  categories: '',
  is_featured: false,
})

const editOpen = ref(false)
const editing = ref(false)
const editForm = reactive({
  id: '',
  title: '',
  prompt: '',
  description: '',
  categories: '',
  is_featured: false,
})

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) {
    message.error('管理员密钥已过期，请重新验证。')
    emit('auth-expired')
    return
  }
  message.error(error instanceof Error ? error.message : fallback)
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : '-'
}

function parseCategories(value: string) {
  return value.split(/[,，]/).map(item => item.trim()).filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    const [candidateData, permanent] = await Promise.all([
      adminFetchInspirationCandidates({ limit: 100 }),
      adminFetchInspirations({ limit: 100 }),
    ])
    candidates.value = candidateData.items
    inspirations.value = permanent
  } catch (error) {
    handleError(error, '社区内容加载失败。')
  } finally {
    loading.value = false
  }
}

async function collect(candidate: AdminInspirationCandidate) {
  collectingId.value = candidate.job_id
  try {
    const created = await adminCreateInspirationFromJob(candidate.job_id)
    inspirations.value.unshift(created)
    candidates.value = candidates.value.filter(item => item.job_id !== candidate.job_id)
    message.success('已收录为独立永久社区内容。')
  } catch (error) {
    handleError(error, '收录失败。')
  } finally {
    collectingId.value = ''
  }
}

function onImportFile(event: Event) {
  importFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submitImport() {
  if (!importForm.title.trim() || !importForm.prompt.trim() || !importForm.source.trim() || !importFile.value) {
    message.warning('请填写标题、提示词、来源标识并选择图片。')
    return
  }
  const body = new FormData()
  body.append('title', importForm.title.trim())
  body.append('prompt', importForm.prompt.trim())
  body.append('source', importForm.source.trim())
  body.append('language', 'zh')
  body.append('is_featured', String(importForm.is_featured))
  body.append('image', importFile.value)
  if (importForm.description.trim()) body.append('description', importForm.description.trim())
  if (importForm.source_url.trim()) body.append('source_url', importForm.source_url.trim())
  if (importForm.author_name.trim()) body.append('author_name', importForm.author_name.trim())
  const categories = parseCategories(importForm.categories)
  if (categories.length) body.append('categories', JSON.stringify(categories))

  importing.value = true
  try {
    await adminCreateInspiration(body)
    importOpen.value = false
    Object.assign(importForm, {
      title: '', prompt: '', description: '', source: 'admin-imported',
      source_url: '', author_name: '', categories: '', is_featured: false,
    })
    importFile.value = null
    await load()
    message.success('永久社区内容已导入。')
  } catch (error) {
    handleError(error, '导入失败。')
  } finally {
    importing.value = false
  }
}

function openEdit(item: AdminInspirationItem) {
  Object.assign(editForm, {
    id: item.id,
    title: item.title,
    prompt: item.prompt,
    description: item.description ?? '',
    categories: item.categories?.join('，') ?? '',
    is_featured: item.is_featured,
  })
  editOpen.value = true
}

async function saveEdit() {
  if (!editForm.title.trim() || !editForm.prompt.trim()) {
    message.warning('标题和提示词不能为空。')
    return
  }
  editing.value = true
  try {
    const updated = await adminUpdateInspiration(editForm.id, {
      title: editForm.title.trim(),
      prompt: editForm.prompt.trim(),
      description: editForm.description.trim() || null,
      categories: parseCategories(editForm.categories),
      is_featured: editForm.is_featured,
    })
    const index = inspirations.value.findIndex(item => item.id === updated.id)
    if (index >= 0) inspirations.value.splice(index, 1, updated)
    editOpen.value = false
    message.success('社区内容已更新。')
  } catch (error) {
    handleError(error, '保存失败。')
  } finally {
    editing.value = false
  }
}

function remove(item: AdminInspirationItem) {
  dialog.warning({
    title: '撤下社区内容',
    content: `确定撤下“${item.title}”吗？对应的永久媒体也会进入清理流程。`,
    positiveText: '撤下',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      try {
        await adminDeleteInspiration(item.id)
        inspirations.value = inspirations.value.filter(entry => entry.id !== item.id)
        message.success('内容已撤下。')
      } catch (error) {
        handleError(error, '撤下失败。')
      }
    },
  })
}

const candidateColumns: DataTableColumns<AdminInspirationCandidate> = [
  { title: '预览', key: 'image_url', width: 78, render: row => row.image_url ? h('img', { src: row.image_url, alt: '', style: 'width:48px;height:48px;object-fit:cover;border-radius:4px' }) : '-' },
  { title: '提示词', key: 'prompt', minWidth: 280, ellipsis: { tooltip: true } },
  { title: '作者', key: 'display_name', width: 130, render: row => row.display_name || row.username || '-' },
  { title: '完成时间', key: 'finished_at', width: 175, render: row => formatDate(row.finished_at) },
  { title: '操作', key: 'actions', width: 110, fixed: 'right', render: row => h(NButton, { size: 'tiny', type: 'primary', loading: collectingId.value === row.job_id, onClick: () => collect(row) }, { icon: () => h(Check, { size: 14 }), default: () => '收录' }) },
]

const inspirationColumns: DataTableColumns<AdminInspirationItem> = [
  { title: '预览', key: 'image_url', width: 78, render: row => h('img', { src: row.image_url, alt: '', style: 'width:48px;height:48px;object-fit:cover;border-radius:4px' }) },
  { title: '标题', key: 'title', minWidth: 180 },
  { title: '来源', key: 'source', width: 150, render: row => h(NTag, { size: 'small', bordered: false }, { default: () => row.source === 'community-curated' ? '管理员精选' : row.source }) },
  { title: '收录时间', key: 'created_at', width: 175, render: row => formatDate(row.created_at) },
  {
    title: '操作', key: 'actions', width: 170, fixed: 'right', render: row => h(NSpace, { size: 6, wrap: false }, { default: () => [
      h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { icon: () => h(Pencil, { size: 14 }), default: () => '编辑' }),
      h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => remove(row) }, { icon: () => h(Trash2, { size: 14 }), default: () => '撤下' }),
    ] }),
  },
]

onMounted(load)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Community</p>
        <h1>社区内容</h1>
        <span>公开作品通过审核后复制为永久社区资产；原作品到期或删除不会影响收录内容。</span>
      </div>
      <NSpace>
        <NButton type="primary" @click="importOpen = true"><template #icon><Plus :size="15" /></template>手动导入</NButton>
        <NButton :loading="loading" @click="load"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
      </NSpace>
    </header>

    <NSpin :show="loading">
      <NTabs type="line" animated>
        <NTabPane name="candidates" tab="收录候选">
          <NEmpty v-if="!loading && candidates.length === 0" description="暂无符合收录条件的公开作品" class="section-empty" />
          <NDataTable v-else :columns="candidateColumns" :data="candidates" :row-key="row => row.job_id" size="small" :single-line="false" :scroll-x="780" />
        </NTabPane>
        <NTabPane name="published" tab="已收录内容">
          <NEmpty v-if="!loading && inspirations.length === 0" description="还没有永久社区内容" class="section-empty" />
          <NDataTable v-else :columns="inspirationColumns" :data="inspirations" :row-key="row => row.id" size="small" :single-line="false" :scroll-x="820" />
        </NTabPane>
      </NTabs>
    </NSpin>

    <NModal v-model:show="importOpen" preset="card" title="导入永久社区内容" class="community-modal" :mask-closable="!importing">
      <NForm label-placement="top">
        <NFormItem label="标题" required><NInput v-model:value="importForm.title" maxlength="256" /></NFormItem>
        <NFormItem label="提示词" required><NInput v-model:value="importForm.prompt" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" /></NFormItem>
        <NFormItem label="描述"><NInput v-model:value="importForm.description" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" /></NFormItem>
        <div class="form-grid">
          <NFormItem label="来源标识" required><NInput v-model:value="importForm.source" maxlength="128" /></NFormItem>
          <NFormItem label="作者"><NInput v-model:value="importForm.author_name" maxlength="128" /></NFormItem>
        </div>
        <NFormItem label="来源链接"><NInput v-model:value="importForm.source_url" placeholder="可选" /></NFormItem>
        <NFormItem label="分类"><NInput v-model:value="importForm.categories" placeholder="使用逗号分隔" /></NFormItem>
        <NFormItem label="图片" required>
          <input type="file" accept="image/png,image/jpeg,image/webp" @change="onImportFile" />
        </NFormItem>
        <NFormItem label="首页精选"><NSwitch v-model:value="importForm.is_featured" /></NFormItem>
      </NForm>
      <template #footer><NSpace justify="end"><NButton :disabled="importing" @click="importOpen = false">取消</NButton><NButton type="primary" :loading="importing" @click="submitImport">上传并保存</NButton></NSpace></template>
    </NModal>

    <NModal v-model:show="editOpen" preset="card" title="编辑社区内容" class="community-modal" :mask-closable="!editing">
      <NForm label-placement="top">
        <NFormItem label="标题" required><NInput v-model:value="editForm.title" maxlength="256" /></NFormItem>
        <NFormItem label="提示词" required><NInput v-model:value="editForm.prompt" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" /></NFormItem>
        <NFormItem label="描述"><NInput v-model:value="editForm.description" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" /></NFormItem>
        <NFormItem label="分类"><NInput v-model:value="editForm.categories" placeholder="使用逗号分隔" /></NFormItem>
        <NFormItem label="首页精选"><NSwitch v-model:value="editForm.is_featured" /></NFormItem>
      </NForm>
      <template #footer><NSpace justify="end"><NButton :disabled="editing" @click="editOpen = false">取消</NButton><NButton type="primary" :loading="editing" @click="saveEdit">保存</NButton></NSpace></template>
    </NModal>
  </section>
</template>

<style scoped>
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.community-modal { width: min(680px, calc(100vw - 32px)); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; gap: 0; } }
</style>
