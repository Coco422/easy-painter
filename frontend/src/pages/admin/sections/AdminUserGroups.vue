<script setup lang="ts">
import { h, onMounted, reactive, ref } from 'vue'
import {
  NButton, NDataTable, NEmpty, NForm, NFormItem, NInput, NInputNumber, NModal,
  NSpace, NSpin, NSwitch, NTag, useDialog, useMessage,
  type DataTableColumns, type FormInst, type FormRules,
} from 'naive-ui'
import { Plus, RefreshCw } from 'lucide-vue-next'

import { ApiError, adminCreateUserGroup, adminDeleteUserGroup, adminFetchUserGroups, adminUpdateUserGroup } from '@/lib/api'
import type { UserGroup } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()
const groups = ref<UserGroup[]>([])
const loading = ref(false)
const saving = ref(false)
const modalOpen = ref(false)
const editingCode = ref<string | null>(null)
const formRef = ref<FormInst | null>(null)
const form = reactive({
  code: '', name: '', description: '', billing_multiplier_bps: 10000,
  generated_retention_hours: 24, reference_retention_hours: 24, max_reference_images: 3,
  is_enabled: true, is_default: false,
})
const rules: FormRules = {
  code: { required: true, pattern: /^[a-z][a-z0-9_-]{1,63}$/, message: '使用 2–64 位小写字母、数字、_ 或 -，且以字母开头', trigger: ['input', 'blur'] },
  name: { required: true, message: '请输入名称', trigger: ['input', 'blur'] },
}

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) { message.error('管理员密钥已过期，请重新验证。'); emit('auth-expired'); return }
  message.error(error instanceof Error ? error.message : fallback)
}
function multiplier(bps: number) { return `${(bps / 10000).toLocaleString(undefined, { maximumFractionDigits: 2 })}×` }
async function loadGroups() {
  loading.value = true
  try { groups.value = await adminFetchUserGroups() } catch (error) { handleError(error, '用户组加载失败。') } finally { loading.value = false }
}
function resetForm() { Object.assign(form, { code: '', name: '', description: '', billing_multiplier_bps: 10000, generated_retention_hours: 24, reference_retention_hours: 24, max_reference_images: 3, is_enabled: true, is_default: false }) }
function openCreate() { editingCode.value = null; resetForm(); formRef.value?.restoreValidation(); modalOpen.value = true }
function openEdit(group: UserGroup) { editingCode.value = group.code; Object.assign(form, group); formRef.value?.restoreValidation(); modalOpen.value = true }
async function saveGroup() {
  try { await formRef.value?.validate() } catch { return }
  saving.value = true
  try {
    const data = { ...form }
    const saved = editingCode.value ? await adminUpdateUserGroup(editingCode.value, data) : await adminCreateUserGroup(data)
    const index = groups.value.findIndex((group) => group.code === saved.code)
    if (index < 0) groups.value.push(saved); else groups.value.splice(index, 1, saved)
    modalOpen.value = false
    message.success(editingCode.value ? '用户组已更新。新策略只影响后续任务和上传。' : '用户组已创建。')
  } catch (error) { handleError(error, '保存用户组失败。') } finally { saving.value = false }
}
function deleteGroup(group: UserGroup) {
  dialog.warning({ title: '删除用户组', content: `确定删除“${group.name}”吗？有成员的用户组不能删除。`, positiveText: '删除', negativeText: '取消', positiveButtonProps: { type: 'error' }, async onPositiveClick() {
    try { await adminDeleteUserGroup(group.code); groups.value = groups.value.filter((item) => item.code !== group.code); message.success('用户组已删除。') } catch (error) { handleError(error, '删除用户组失败。') }
  }})
}
const columns: DataTableColumns<UserGroup> = [
  { title: '用户组', key: 'name', minWidth: 150, render: row => h('div', [h('strong', row.name), h('small', { style: 'display:block;color:var(--text-muted)' }, row.code)]) },
  { title: '倍率', key: 'billing_multiplier_bps', width: 90, render: row => multiplier(row.billing_multiplier_bps) },
  { title: '生成图 / 参考图', key: 'retention', minWidth: 145, render: row => `${row.generated_retention_hours}h / ${row.reference_retention_hours}h` },
  { title: '参考图上限', key: 'max_reference_images', width: 110, render: row => `${row.max_reference_images} 张` },
  { title: '成员', key: 'user_count', width: 70 },
  { title: '状态', key: 'is_enabled', width: 115, render: row => h(NSpace, { size: 4 }, { default: () => [row.is_default ? h(NTag, { size: 'small', type: 'warning', bordered: false }, { default: () => '默认' }) : null, h(NTag, { size: 'small', type: row.is_enabled ? 'success' : 'default', bordered: false }, { default: () => row.is_enabled ? '启用' : '停用' })] }) },
  { title: '操作', key: 'actions', width: 130, fixed: 'right', render: row => h(NSpace, { size: 6, wrap: false }, { default: () => [h(NButton, { size: 'tiny', onClick: () => openEdit(row) }, { default: () => '编辑' }), h(NButton, { size: 'tiny', type: 'error', ghost: true, disabled: row.code === 'standard' || row.is_default || row.user_count > 0, onClick: () => deleteGroup(row) }, { default: () => '删除' })] }) },
]
onMounted(loadGroups)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header"><div><p class="section-kicker">Groups</p><h1>用户组</h1><span>统一配置结算倍率和媒体保留策略；变更只影响后续任务与上传。</span></div><NSpace><NButton :loading="loading" @click="loadGroups"><template #icon><RefreshCw :size="15" /></template>刷新</NButton><NButton type="primary" @click="openCreate"><template #icon><Plus :size="16" /></template>新增用户组</NButton></NSpace></header>
    <NSpin :show="loading"><NEmpty v-if="!loading && groups.length === 0" description="还没有用户组" class="section-empty" /><NDataTable v-else :columns="columns" :data="groups" :row-key="row => row.code" size="small" :single-line="false" :scroll-x="900" :max-height="680" virtual-scroll /></NSpin>
    <NModal v-model:show="modalOpen" preset="card" class="admin-form-modal" :title="editingCode ? '编辑用户组' : '新增用户组'" :mask-closable="!saving">
      <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
        <NFormItem label="代码" path="code"><NInput v-model:value="form.code" :disabled="Boolean(editingCode)" placeholder="standard / vip" /></NFormItem>
        <NFormItem label="名称" path="name"><NInput v-model:value="form.name" /></NFormItem>
        <NFormItem label="说明"><NInput v-model:value="form.description" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" /></NFormItem>
        <div class="policy-grid"><NFormItem label="结算倍率（万分比）"><NInputNumber v-model:value="form.billing_multiplier_bps" :min="0" :max="100000" /><small>{{ multiplier(form.billing_multiplier_bps) }}</small></NFormItem><NFormItem label="生成图保留（小时）"><NInputNumber v-model:value="form.generated_retention_hours" :min="1" :max="87600" /></NFormItem><NFormItem label="参考图保留（小时）"><NInputNumber v-model:value="form.reference_retention_hours" :min="1" :max="87600" /></NFormItem><NFormItem label="参考图上限"><NInputNumber v-model:value="form.max_reference_images" :min="0" :max="10000" /></NFormItem></div>
        <NSpace><NFormItem label="启用"><NSwitch v-model:value="form.is_enabled" :disabled="editingCode === 'standard' && form.is_default" /></NFormItem><NFormItem label="设为默认"><NSwitch v-model:value="form.is_default" /></NFormItem></NSpace>
      </NForm><template #footer><NSpace justify="end"><NButton :disabled="saving" @click="modalOpen = false">取消</NButton><NButton type="primary" :loading="saving" @click="saveGroup">保存</NButton></NSpace></template>
    </NModal>
  </section>
</template>

<style scoped>
.policy-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.policy-grid small { display: block; margin-top: 5px; color: var(--text-muted); }
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
@media (max-width: 620px) { .policy-grid { grid-template-columns: 1fr; } }
</style>
