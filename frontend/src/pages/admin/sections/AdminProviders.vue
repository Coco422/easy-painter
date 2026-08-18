<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NSpin,
  useDialog,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { Eye, EyeOff, Plus, RefreshCw } from 'lucide-vue-next'

import {
  ApiError,
  adminCreateProvider,
  adminDeleteProvider,
  adminFetchProviders,
  adminUpdateProvider,
} from '@/lib/api'
import type { UpstreamProvider } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()

const providers = ref<UpstreamProvider[]>([])
const loading = ref(false)
const saving = ref(false)
const revealedKeys = ref(new Set<string>())
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<FormInst | null>(null)

const form = reactive({
  name: '',
  base_url: '',
  api_key: '',
  timeout_seconds: 700,
  default_output_format: 'jpeg',
  default_quality: 'high',
})

const rules: FormRules = {
  name: { required: true, message: '请输入上游名称', trigger: ['input', 'blur'] },
  base_url: { required: true, message: '请输入 API 地址', trigger: ['input', 'blur'] },
  api_key: { required: true, message: '请输入 API 密钥', trigger: ['input', 'blur'] },
  timeout_seconds: { type: 'number', required: true, min: 1, message: '超时时间必须大于 0', trigger: ['input', 'blur'] },
}

const outputFormatOptions = [
  { label: 'JPEG', value: 'jpeg' },
  { label: 'PNG', value: 'png' },
  { label: 'WebP', value: 'webp' },
]
const qualityOptions = ['high', 'medium', 'low', 'auto'].map((value) => ({ label: value, value }))

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) {
    message.error('管理员密钥已过期，请重新验证。')
    emit('auth-expired')
    return
  }
  message.error(error instanceof Error ? error.message : fallback)
}

async function loadProviders() {
  loading.value = true
  try {
    providers.value = await adminFetchProviders()
  } catch (error) {
    handleError(error, '上游列表加载失败。')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.name = ''
  form.base_url = ''
  form.api_key = ''
  form.timeout_seconds = 700
  form.default_output_format = 'jpeg'
  form.default_quality = 'high'
  formRef.value?.restoreValidation()
}

function openCreate() {
  editingId.value = null
  resetForm()
  modalOpen.value = true
}

function openEdit(provider: UpstreamProvider) {
  editingId.value = provider.id
  form.name = provider.name
  form.base_url = provider.base_url
  form.api_key = provider.api_key
  form.timeout_seconds = provider.timeout_seconds
  form.default_output_format = provider.default_output_format
  form.default_quality = provider.default_quality
  formRef.value?.restoreValidation()
  modalOpen.value = true
}

async function saveProvider() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      const updated = await adminUpdateProvider(editingId.value, { ...form })
      const index = providers.value.findIndex((item) => item.id === updated.id)
      if (index >= 0) providers.value.splice(index, 1, updated)
      message.success('上游配置已更新。')
    } else {
      const created = await adminCreateProvider({ ...form })
      providers.value.push(created)
      message.success('上游已创建。')
    }
    modalOpen.value = false
  } catch (error) {
    handleError(error, editingId.value ? '上游更新失败。' : '上游创建失败。')
  } finally {
    saving.value = false
  }
}

function deleteProvider(provider: UpstreamProvider) {
  dialog.warning({
    title: '删除上游',
    content: `确定删除“${provider.name}”吗？需要先删除或迁移其关联模型。`,
    positiveText: '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      try {
        await adminDeleteProvider(provider.id)
        providers.value = providers.value.filter((item) => item.id !== provider.id)
        message.success('上游已删除。')
      } catch (error) {
        handleError(error, '上游删除失败。')
      }
    },
  })
}

function toggleKey(providerId: string) {
  const next = new Set(revealedKeys.value)
  if (next.has(providerId)) next.delete(providerId)
  else next.add(providerId)
  revealedKeys.value = next
}

function maskKey(key: string) {
  if (key.length <= 8) return '••••••••'
  return `${key.slice(0, 4)}${'•'.repeat(Math.min(12, key.length - 8))}${key.slice(-4)}`
}

const columns = computed<DataTableColumns<UpstreamProvider>>(() => [
  { title: '名称', key: 'name', minWidth: 130 },
  {
    title: 'API 地址',
    key: 'base_url',
    minWidth: 230,
    ellipsis: { tooltip: true },
  },
  {
    title: 'API Key',
    key: 'api_key',
    minWidth: 220,
    render(row) {
      const revealed = revealedKeys.value.has(row.id)
      return h('div', { class: 'secret-cell' }, [
        h('code', revealed ? row.api_key : maskKey(row.api_key)),
        h(
          NButton,
          { quaternary: true, circle: true, size: 'tiny', title: revealed ? '隐藏密钥' : '显示密钥', onClick: () => toggleKey(row.id) },
          { icon: () => h(revealed ? EyeOff : Eye, { size: 14 }) },
        ),
      ])
    },
  },
  { title: '超时', key: 'timeout_seconds', width: 90, render: (row) => `${row.timeout_seconds}s` },
  {
    title: '默认输出',
    key: 'default_output_format',
    width: 130,
    render: (row) => `${row.default_output_format} / ${row.default_quality}`,
  },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    fixed: 'right',
    render(row) {
      return h(NSpace, { size: 6, wrap: false }, {
        default: () => [
          h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => deleteProvider(row) }, { default: () => '删除' }),
        ],
      })
    },
  },
])

onMounted(loadProviders)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Providers</p>
        <h1>上游管理</h1>
        <span>配置图像生成服务的地址、密钥和默认输出参数。</span>
      </div>
      <NSpace>
        <NButton :loading="loading" @click="loadProviders"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
        <NButton type="primary" @click="openCreate"><template #icon><Plus :size="16" /></template>新增上游</NButton>
      </NSpace>
    </header>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && providers.length === 0" description="还没有上游配置" class="section-empty" />
      <NDataTable
        v-else
        :columns="columns"
        :data="providers"
        :row-key="(row: UpstreamProvider) => row.id"
        :bordered="true"
        :single-line="false"
        size="small"
        :scroll-x="980"
        :max-height="680"
        virtual-scroll
      />
    </NSpin>

    <NModal v-model:show="modalOpen" preset="card" :title="editingId ? '编辑上游' : '新增上游'" class="admin-form-modal" :mask-closable="!saving">
      <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
        <NFormItem label="名称" path="name"><NInput v-model:value="form.name" maxlength="128" /></NFormItem>
        <NFormItem label="API 地址" path="base_url"><NInput v-model:value="form.base_url" maxlength="512" placeholder="https://api.example.com/v1" /></NFormItem>
        <NFormItem label="API 密钥" path="api_key"><NInput v-model:value="form.api_key" type="password" show-password-on="click" maxlength="512" /></NFormItem>
        <div class="form-grid-3">
          <NFormItem label="超时（秒）" path="timeout_seconds"><NInputNumber v-model:value="form.timeout_seconds" :min="1" :max="3600" /></NFormItem>
          <NFormItem label="输出格式"><NSelect v-model:value="form.default_output_format" :options="outputFormatOptions" /></NFormItem>
          <NFormItem label="质量"><NSelect v-model:value="form.default_quality" :options="qualityOptions" /></NFormItem>
        </div>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="saving" @click="modalOpen = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="saveProvider">保存</NButton>
        </NSpace>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.secret-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.secret-cell code { overflow: hidden; color: var(--text-secondary); font: 12px/1.4 var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.form-grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 680px) { .form-grid-3 { grid-template-columns: 1fr; gap: 0; } }
</style>
