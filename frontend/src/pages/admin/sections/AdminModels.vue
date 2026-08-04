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
  NSwitch,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { Plus, RefreshCw } from 'lucide-vue-next'

import {
  ApiError,
  adminCreateModel,
  adminDeleteModel,
  adminFetchModels,
  adminFetchProviders,
  adminUpdateModel,
} from '@/lib/api'
import type { ModelConfig, UpstreamProvider } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()

const models = ref<ModelConfig[]>([])
const providers = ref<UpstreamProvider[]>([])
const loading = ref(false)
const saving = ref(false)
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<FormInst | null>(null)

const form = reactive({
  id: '',
  label: '',
  provider_id: '',
  enabled: true,
  supports_reference_image: true,
  credit_cost: 1,
  sort_order: 0,
  supported_sizes: '',
})

const rules: FormRules = {
  id: { required: true, message: '请输入模型 ID', trigger: ['input', 'blur'] },
  label: { required: true, message: '请输入显示名称', trigger: ['input', 'blur'] },
  provider_id: { required: true, message: '请选择上游', trigger: ['change', 'blur'] },
  credit_cost: { type: 'number', required: true, min: 1, message: '单张消耗至少为 1', trigger: ['input', 'blur'] },
}

const providerOptions = computed(() => providers.value.map((item) => ({ label: item.name, value: item.id })))
const providerNameMap = computed(() => new Map(providers.value.map((item) => [item.id, item.name])))

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) {
    message.error('管理员密钥已过期，请重新验证。')
    emit('auth-expired')
    return
  }
  message.error(error instanceof Error ? error.message : fallback)
}

async function loadData() {
  loading.value = true
  try {
    const [modelItems, providerItems] = await Promise.all([adminFetchModels(), adminFetchProviders()])
    models.value = modelItems
    providers.value = providerItems
  } catch (error) {
    handleError(error, '模型配置加载失败。')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.id = ''
  form.label = ''
  form.provider_id = providers.value[0]?.id ?? ''
  form.enabled = true
  form.supports_reference_image = true
  form.credit_cost = 1
  form.sort_order = 0
  form.supported_sizes = ''
  formRef.value?.restoreValidation()
}

function openCreate() {
  editingId.value = null
  resetForm()
  modalOpen.value = true
}

function openEdit(model: ModelConfig) {
  editingId.value = model.id
  form.id = model.id
  form.label = model.label
  form.provider_id = model.provider_id
  form.enabled = model.enabled
  form.supports_reference_image = model.supports_reference_image
  form.credit_cost = model.credit_cost
  form.sort_order = model.sort_order
  form.supported_sizes = model.supported_sizes.join(', ')
  formRef.value?.restoreValidation()
  modalOpen.value = true
}

function parseSizes() {
  return [...new Set(form.supported_sizes.split(',').map((item) => item.trim()).filter(Boolean))]
}

async function saveModel() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  const payload = {
    provider_id: form.provider_id,
    label: form.label,
    enabled: form.enabled,
    supports_reference_image: form.supports_reference_image,
    supported_sizes: parseSizes(),
    sort_order: form.sort_order,
    credit_cost: form.credit_cost,
  }
  try {
    if (editingId.value) {
      const updated = await adminUpdateModel(editingId.value, payload)
      const index = models.value.findIndex((item) => item.id === updated.id)
      if (index >= 0) models.value.splice(index, 1, updated)
      message.success('模型配置已更新。')
    } else {
      const created = await adminCreateModel({ id: form.id, ...payload })
      models.value.push(created)
      models.value.sort((a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id))
      message.success('模型已创建。')
    }
    modalOpen.value = false
  } catch (error) {
    handleError(error, editingId.value ? '模型更新失败。' : '模型创建失败。')
  } finally {
    saving.value = false
  }
}

function deleteModel(model: ModelConfig) {
  dialog.warning({
    title: '删除模型',
    content: `确定删除“${model.label}”吗？`,
    positiveText: '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      try {
        await adminDeleteModel(model.id)
        models.value = models.value.filter((item) => item.id !== model.id)
        message.success('模型已删除。')
      } catch (error) {
        handleError(error, '模型删除失败。')
      }
    },
  })
}

const columns = computed<DataTableColumns<ModelConfig>>(() => [
  { title: '模型 ID', key: 'id', minWidth: 180, ellipsis: { tooltip: true }, className: 'mono-cell' },
  { title: '显示名称', key: 'label', minWidth: 160 },
  { title: '上游', key: 'provider_id', minWidth: 130, render: (row) => providerNameMap.value.get(row.provider_id) ?? row.provider_id },
  {
    title: '参考图', key: 'supports_reference_image', width: 90,
    render: (row) => h(NTag, { size: 'small', type: row.supports_reference_image ? 'success' : 'default', bordered: false }, { default: () => row.supports_reference_image ? '支持' : '不支持' }),
  },
  { title: '丝/张', key: 'credit_cost', width: 75 },
  { title: '排序', key: 'sort_order', width: 70 },
  {
    title: '状态', key: 'enabled', width: 80,
    render: (row) => h(NTag, { size: 'small', type: row.enabled ? 'success' : 'warning', bordered: false }, { default: () => row.enabled ? '启用' : '停用' }),
  },
  {
    title: '操作', key: 'actions', width: 150, fixed: 'right',
    render(row) {
      return h(NSpace, { size: 6, wrap: false }, { default: () => [
        h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => deleteModel(row) }, { default: () => '删除' }),
      ] })
    },
  },
])

onMounted(loadData)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Models</p>
        <h1>模型管理</h1>
        <span>控制模型能力、生成尺寸、排序和单张消耗。</span>
      </div>
      <NSpace>
        <NButton :loading="loading" @click="loadData"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
        <NButton type="primary" :disabled="providers.length === 0" @click="openCreate"><template #icon><Plus :size="16" /></template>新增模型</NButton>
      </NSpace>
    </header>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && models.length === 0" description="还没有模型配置" class="section-empty" />
      <NDataTable v-else :columns="columns" :data="models" :row-key="(row: ModelConfig) => row.id" size="small" :single-line="false" :scroll-x="1050" />
    </NSpin>

    <NModal v-model:show="modalOpen" preset="card" :title="editingId ? '编辑模型' : '新增模型'" class="admin-form-modal" :mask-closable="!saving">
      <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
        <NFormItem label="模型 ID" path="id"><NInput v-model:value="form.id" :disabled="Boolean(editingId)" maxlength="128" /></NFormItem>
        <NFormItem label="显示名称" path="label"><NInput v-model:value="form.label" maxlength="256" /></NFormItem>
        <NFormItem label="上游" path="provider_id"><NSelect v-model:value="form.provider_id" :options="providerOptions" filterable /></NFormItem>
        <NFormItem label="支持尺寸（逗号分隔，留空不限制）"><NInput v-model:value="form.supported_sizes" placeholder="1024x1024, 1280x720" /></NFormItem>
        <div class="form-grid-2">
          <NFormItem label="丝/张" path="credit_cost"><NInputNumber v-model:value="form.credit_cost" :min="1" /></NFormItem>
          <NFormItem label="排序"><NInputNumber v-model:value="form.sort_order" /></NFormItem>
          <NFormItem label="支持参考图"><NSwitch v-model:value="form.supports_reference_image" /></NFormItem>
          <NFormItem label="启用模型"><NSwitch v-model:value="form.enabled" /></NFormItem>
        </div>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="saving" @click="modalOpen = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="saveModel">保存</NButton>
        </NSpace>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.form-grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
@media (max-width: 620px) { .form-grid-2 { grid-template-columns: 1fr; } }
</style>
