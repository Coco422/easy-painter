<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
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
import { GripVertical, Plus, RefreshCw } from 'lucide-vue-next'

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
const reordering = ref(false)
const draggedId = ref<string | null>(null)
const dragOverId = ref<string | null>(null)
const dragPosition = ref<'before' | 'after' | null>(null)
const statusSavingIds = ref(new Set<string>())

const form = reactive({
  id: '',
  label: '',
  provider_id: '',
  enabled: true,
  supports_reference_image: true,
  credit_cost: 2,
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
    if (modelItems.some((item, index) => item.sort_order !== index)) {
      try {
        await persistModelOrder(modelItems)
      } catch (error) {
        handleError(error, '模型排序自动编号失败。')
      }
    }
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
  form.credit_cost = 2
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
    credit_cost: form.credit_cost,
  }
  try {
    if (editingId.value) {
      const updated = await adminUpdateModel(editingId.value, payload)
      const index = models.value.findIndex((item) => item.id === updated.id)
      if (index >= 0) models.value.splice(index, 1, updated)
      message.success('模型配置已更新。')
    } else {
      const created = await adminCreateModel({ id: form.id, ...payload, sort_order: models.value.length })
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
        try {
          await persistModelOrder(models.value)
        } catch (error) {
          handleError(error, '模型已删除，但排序重新编号失败。')
        }
        message.success('模型已删除。')
      } catch (error) {
        handleError(error, '模型删除失败。')
      }
    },
  })
}

function setStatusSaving(modelId: string, savingStatus: boolean) {
  const next = new Set(statusSavingIds.value)
  if (savingStatus) next.add(modelId)
  else next.delete(modelId)
  statusSavingIds.value = next
}

async function toggleModelEnabled(model: ModelConfig, enabled: boolean) {
  if (model.enabled === enabled || statusSavingIds.value.has(model.id)) return
  const previous = model.enabled
  model.enabled = enabled
  setStatusSaving(model.id, true)
  try {
    const updated = await adminUpdateModel(model.id, { enabled })
    model.enabled = updated.enabled
    message.success(`${model.label} 已${updated.enabled ? '启用' : '停用'}。`)
  } catch (error) {
    model.enabled = previous
    handleError(error, '模型状态更新失败。')
  } finally {
    setStatusSaving(model.id, false)
  }
}

function clearDragState() {
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', handlePointerUp)
  window.removeEventListener('pointercancel', handlePointerCancel)
  draggedId.value = null
  dragOverId.value = null
  dragPosition.value = null
}

function handlePointerCancel() {
  clearDragState()
}

function handlePointerDown(model: ModelConfig, event: PointerEvent) {
  if (reordering.value || statusSavingIds.value.size > 0) {
    event.preventDefault()
    return
  }
  event.preventDefault()
  clearDragState()
  draggedId.value = model.id
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', handlePointerUp, { once: true })
  window.addEventListener('pointercancel', handlePointerCancel, { once: true })
}

function handlePointerMove(event: PointerEvent) {
  if (!draggedId.value || reordering.value) return
  event.preventDefault()
  const row = document.elementFromPoint(event.clientX, event.clientY)?.closest('tr[data-model-id]') as HTMLElement | null | undefined
  const targetId = row?.dataset.modelId
  if (!row || !targetId || targetId === draggedId.value) {
    dragOverId.value = null
    dragPosition.value = null
    return
  }
  const rect = row.getBoundingClientRect()
  dragOverId.value = targetId
  dragPosition.value = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after'
}

function handlePointerUp(event: PointerEvent) {
  event.preventDefault()
  const sourceId = draggedId.value
  const targetId = dragOverId.value
  const position = dragPosition.value
  clearDragState()
  if (!sourceId || !targetId || sourceId === targetId || !position) return
  void moveModel(sourceId, targetId, position)
}

async function moveModel(sourceId: string, targetId: string, position: 'before' | 'after') {
  const next = [...models.value]
  const sourceIndex = next.findIndex((item) => item.id === sourceId)
  if (sourceIndex < 0) return
  const [moved] = next.splice(sourceIndex, 1)
  let targetIndex = next.findIndex((item) => item.id === targetId)
  if (targetIndex < 0) return
  if (position === 'after') targetIndex += 1
  next.splice(targetIndex, 0, moved)

  try {
    await persistModelOrder(next, '模型顺序已保存。')
  } catch (error) {
    handleError(error, '模型顺序保存失败，已恢复服务端顺序。')
  }
}

function handleSortKeydown(model: ModelConfig, event: KeyboardEvent) {
  if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key) || reordering.value) return
  event.preventDefault()
  const sourceIndex = models.value.findIndex((item) => item.id === model.id)
  const targetIndex = sourceIndex + (event.key === 'ArrowUp' ? -1 : 1)
  if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= models.value.length) return
  void moveModel(model.id, models.value[targetIndex].id, event.key === 'ArrowUp' ? 'before' : 'after')
}

async function persistModelOrder(nextOrder: ModelConfig[], successText?: string) {
  const previous = models.value.map((item) => ({ ...item }))
  const normalized = nextOrder.map((item, index) => ({ ...item, sort_order: index }))
  const changed = normalized.filter((item) => {
    const original = nextOrder.find((candidate) => candidate.id === item.id)
    return original?.sort_order !== item.sort_order
  })

  models.value = normalized
  if (changed.length === 0) return

  reordering.value = true
  try {
    const results = await Promise.allSettled(
      changed.map((item) => adminUpdateModel(item.id, { sort_order: item.sort_order })),
    )
    const rejected = results.find((result) => result.status === 'rejected')
    if (rejected?.status === 'rejected') throw rejected.reason
    if (successText) message.success(successText)
  } catch (error) {
    try {
      models.value = await adminFetchModels()
    } catch {
      models.value = previous
    }
    throw error
  } finally {
    reordering.value = false
  }
}

function getRowProps(row: ModelConfig) {
  return {
    'data-model-id': row.id,
    class: [
      row.id === draggedId.value ? 'model-row-dragging' : '',
      row.id === dragOverId.value && dragPosition.value === 'before' ? 'model-row-drop-before' : '',
      row.id === dragOverId.value && dragPosition.value === 'after' ? 'model-row-drop-after' : '',
    ].filter(Boolean).join(' '),
  }
}

const columns = computed<DataTableColumns<ModelConfig>>(() => [
  {
    title: '排序', key: 'drag', width: 68, fixed: 'left',
    render: (row, index) => h('div', { class: 'model-drag-cell' }, [
      h('button', {
        type: 'button',
        class: 'model-drag-handle',
        disabled: reordering.value || statusSavingIds.value.size > 0,
        title: '拖拽调整创作台模型顺序；也可按 Alt + ↑/↓',
        'aria-label': `拖拽调整 ${row.label} 的顺序`,
        'aria-grabbed': row.id === draggedId.value,
        onPointerdown: (event: PointerEvent) => handlePointerDown(row, event),
        onKeydown: (event: KeyboardEvent) => handleSortKeydown(row, event),
      }, [
        h(GripVertical, { size: 14, 'stroke-width': 1.8, 'aria-hidden': true }),
        h('span', { class: 'model-position', 'aria-hidden': true }, String(index + 1).padStart(2, '0')),
      ]),
    ]),
  },
  { title: '模型 ID', key: 'id', minWidth: 180, ellipsis: { tooltip: true }, className: 'mono-cell' },
  { title: '显示名称', key: 'label', minWidth: 160 },
  { title: '上游', key: 'provider_id', minWidth: 130, render: (row) => providerNameMap.value.get(row.provider_id) ?? row.provider_id },
  {
    title: '参考图', key: 'supports_reference_image', width: 90,
    render: (row) => h(NTag, { size: 'small', type: row.supports_reference_image ? 'success' : 'default', bordered: false }, { default: () => row.supports_reference_image ? '支持' : '不支持' }),
  },
  { title: '丝/张', key: 'credit_cost', width: 75 },
  {
    title: '状态', key: 'enabled', width: 112,
    render: (row) => h('div', { class: 'model-status-cell' }, [
      h(NSwitch, {
        value: row.enabled,
        size: 'small',
        loading: statusSavingIds.value.has(row.id),
        disabled: reordering.value,
        'onUpdate:value': (enabled: boolean) => { void toggleModelEnabled(row, enabled) },
      }),
      h('span', { class: row.enabled ? 'status-enabled' : 'status-disabled' }, row.enabled ? '启用' : '停用'),
    ]),
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
onBeforeUnmount(clearDragState)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Models</p>
        <h1>模型管理</h1>
        <span>左侧拖拽决定创作台模型顺序；状态开关切换后自动保存。</span>
      </div>
      <NSpace>
        <NTag v-if="reordering" size="small" type="warning" :bordered="false">正在保存排序…</NTag>
        <NButton :loading="loading" @click="loadData"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
        <NButton type="primary" :disabled="providers.length === 0 || reordering" @click="openCreate"><template #icon><Plus :size="16" /></template>新增模型</NButton>
      </NSpace>
    </header>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && models.length === 0" description="还没有模型配置" class="section-empty" />
      <NDataTable v-else :columns="columns" :data="models" :row-key="(row: ModelConfig) => row.id" :row-props="getRowProps" size="small" :single-line="false" :scroll-x="1080" />
    </NSpin>

    <NModal v-model:show="modalOpen" preset="card" :title="editingId ? '编辑模型' : '新增模型'" class="admin-form-modal" :mask-closable="!saving">
      <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
        <NFormItem label="模型 ID" path="id"><NInput v-model:value="form.id" :disabled="Boolean(editingId)" maxlength="128" /></NFormItem>
        <NFormItem label="显示名称" path="label"><NInput v-model:value="form.label" maxlength="256" /></NFormItem>
        <NFormItem label="上游" path="provider_id"><NSelect v-model:value="form.provider_id" :options="providerOptions" filterable /></NFormItem>
        <NFormItem label="支持尺寸（逗号分隔，留空不限制）"><NInput v-model:value="form.supported_sizes" placeholder="1024x1024, 1280x720" /></NFormItem>
        <div class="form-grid-2">
          <NFormItem label="丝/张" path="credit_cost"><NInputNumber v-model:value="form.credit_cost" :min="1" /></NFormItem>
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
:deep(.model-drag-cell), :deep(.model-status-cell) { display: flex; align-items: center; gap: 7px; }
:deep(.model-drag-handle) {
  appearance: none;
  display: inline-grid;
  grid-template-columns: 14px 18px;
  align-items: center;
  justify-content: center;
  gap: 3px;
  width: 46px;
  height: 28px;
  padding: 0 5px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: color-mix(in srgb, var(--bg-elevated) 72%, transparent);
  color: var(--text-muted);
  font-family: inherit;
  cursor: grab;
  touch-action: none;
  user-select: none;
  transition: color 160ms, border-color 160ms, background 160ms, box-shadow 160ms;
}
:deep(.model-drag-handle svg) { opacity: .72; }
:deep(.model-drag-handle:hover:not(:disabled)) { border-color: var(--border-accent); background: var(--accent-soft); color: var(--accent); }
:deep(.model-drag-handle:focus-visible) { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); color: var(--accent); }
:deep(.model-drag-handle:active:not(:disabled)), :deep(.model-drag-handle[aria-grabbed="true"]) { cursor: grabbing; border-color: var(--border-accent); background: var(--accent-soft); color: var(--accent); }
:deep(.model-drag-handle:disabled) { cursor: wait; opacity: .42; }
:deep(.model-position) { color: currentColor; font: 600 10px/1 var(--font-mono); letter-spacing: .02em; text-align: right; }
:deep(.model-status-cell span) { font-size: 12px; font-weight: 600; }
:deep(.status-enabled) { color: var(--success); }
:deep(.status-disabled) { color: var(--text-muted); }
:deep(.model-row-dragging td) { opacity: .5; background: var(--bg-hover); }
:deep(.model-row-drop-before td) { box-shadow: inset 0 2px 0 var(--accent); }
:deep(.model-row-drop-after td) { box-shadow: inset 0 -2px 0 var(--accent); }
@media (max-width: 620px) { .form-grid-2 { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { :deep(.model-drag-handle) { transition: none; } }
</style>
