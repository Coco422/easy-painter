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
  NInputNumber,
  NPagination,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { ArrowRightLeft, Copy, RefreshCw, Ticket, Wallet } from 'lucide-vue-next'

import {
  ApiError,
  adminAdjustCredits,
  adminFetchCodes,
  adminFetchTransactions,
  adminFetchUsers,
  adminGenerateCodes,
} from '@/lib/api'
import type { CreditTransactionItem, RedemptionCodeItem, UserInfo } from '@/lib/types'

type AdminTransaction = CreditTransactionItem & { id: string; user_id: string; username: string | null }

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()

const users = ref<UserInfo[]>([])
const codes = ref<RedemptionCodeItem[]>([])
const transactions = ref<AdminTransaction[]>([])
const codesLoading = ref(false)
const usersLoading = ref(false)
const transactionsLoading = ref(false)

const codesFilter = ref<'all' | 'unused' | 'used'>('all')
const generateFormRef = ref<FormInst | null>(null)
const generating = ref(false)
const generateForm = reactive({ count: 10, credits: 100, prefix: 'EP' })
const generateResult = ref<string[]>([])
const generateRules: FormRules = {
  count: { type: 'number', required: true, min: 1, max: 1000, message: '数量必须在 1 到 1000 之间', trigger: ['input', 'blur'] },
  credits: { type: 'number', required: true, min: 1, message: '面额必须大于 0', trigger: ['input', 'blur'] },
}

const adjustFormRef = ref<FormInst | null>(null)
const adjusting = ref(false)
const adjustForm = reactive({ user_id: '', amount: 0, reason: '' })
const adjustRules: FormRules = {
  user_id: { required: true, message: '请选择用户', trigger: ['change', 'blur'] },
  amount: {
    type: 'number',
    required: true,
    trigger: ['input', 'blur'],
    validator: (_rule, value) => value !== 0 || new Error('调整数量不能为 0'),
  },
}

const transactionUserId = ref<string | null>(null)
const transactionPage = ref(1)
const transactionPageSize = 50
const transactionPageCount = computed(() => Math.max(1, transactionPage.value + (transactions.value.length === transactionPageSize ? 1 : 0)))
const userOptions = computed(() => users.value.map((user) => ({ label: `${user.username}（${user.credits ?? 0} 丝）`, value: user.id })))
const transactionUserOptions = computed(() => [{ label: '全部用户', value: '' }, ...users.value.map((user) => ({ label: user.username, value: user.id }))])

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

async function loadUsers() {
  usersLoading.value = true
  try {
    users.value = await adminFetchUsers()
  } catch (error) {
    handleError(error, '用户列表加载失败。')
  } finally {
    usersLoading.value = false
  }
}

async function loadCodes() {
  codesLoading.value = true
  try {
    codes.value = await adminFetchCodes(codesFilter.value)
  } catch (error) {
    handleError(error, '兑换码加载失败。')
  } finally {
    codesLoading.value = false
  }
}

async function loadTransactions() {
  transactionsLoading.value = true
  try {
    let items = await adminFetchTransactions(transactionUserId.value || undefined, transactionPage.value)
    if (items.length === 0 && transactionPage.value > 1) {
      transactionPage.value -= 1
      items = await adminFetchTransactions(transactionUserId.value || undefined, transactionPage.value)
    }
    transactions.value = items
  } catch (error) {
    handleError(error, '消费记录加载失败。')
  } finally {
    transactionsLoading.value = false
  }
}

async function generateCodes() {
  try {
    await generateFormRef.value?.validate()
  } catch {
    return
  }
  generating.value = true
  try {
    const result = await adminGenerateCodes({ ...generateForm })
    generateResult.value = result.codes
    await loadCodes()
    message.success(`已生成 ${result.codes.length} 个兑换码。`)
  } catch (error) {
    handleError(error, '兑换码生成失败。')
  } finally {
    generating.value = false
  }
}

async function copyGeneratedCodes() {
  if (generateResult.value.length === 0) return
  try {
    await navigator.clipboard.writeText(generateResult.value.join('\n'))
    message.success('兑换码已复制到剪贴板。')
  } catch {
    message.error('复制失败，请手动选择文本复制。')
  }
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    message.success(`兑换码 ${code} 已复制。`)
  } catch {
    message.error('复制失败，请手动选择兑换码。')
  }
}

async function adjustCredits() {
  try {
    await adjustFormRef.value?.validate()
  } catch {
    return
  }
  adjusting.value = true
  try {
    const result = await adminAdjustCredits(adjustForm.user_id, {
      amount: adjustForm.amount,
      reason: adjustForm.reason || undefined,
    })
    const user = users.value.find((item) => item.id === adjustForm.user_id)
    if (user) user.credits = result.credits
    adjustForm.amount = 0
    adjustForm.reason = ''
    await loadTransactions()
    message.success(`余额调整成功，当前为 ${result.credits} 丝。`)
  } catch (error) {
    handleError(error, '余额调整失败。')
  } finally {
    adjusting.value = false
  }
}

function changeCodesFilter(value: 'all' | 'unused' | 'used') {
  codesFilter.value = value
  void loadCodes()
}

function changeTransactionUser(value: string | null) {
  transactionUserId.value = value || null
  transactionPage.value = 1
  void loadTransactions()
}

function changeTransactionPage(page: number) {
  transactionPage.value = page
  void loadTransactions()
}

async function refreshAll() {
  await Promise.all([loadUsers(), loadCodes(), loadTransactions()])
}

const codeColumns: DataTableColumns<RedemptionCodeItem> = [
  {
    title: '兑换码', key: 'code', minWidth: 230,
    render: (row) => h('div', { class: 'code-cell' }, [
      h('code', { class: 'code-value' }, row.code),
      h(NButton, {
        size: 'tiny',
        quaternary: true,
        title: '复制兑换码',
        onClick: () => copyCode(row.code),
      }, {
        icon: () => h(Copy, { size: 13 }),
        default: () => '复制',
      }),
    ]),
  },
  { title: '面额', key: 'credits', width: 90 },
  {
    title: '状态', key: 'status', width: 90,
    render: (row) => h(NTag, { size: 'small', type: row.used_by ? 'default' : 'success', bordered: false }, { default: () => row.used_by ? '已使用' : '未使用' }),
  },
  { title: '使用者', key: 'used_by', minWidth: 110, render: (row) => row.used_by ? row.used_by.slice(0, 8) : '-' },
  { title: '使用时间', key: 'used_at', minWidth: 170, render: (row) => formatDate(row.used_at) },
  { title: '创建时间', key: 'created_at', minWidth: 170, render: (row) => formatDate(row.created_at) },
]

const transactionColumns: DataTableColumns<AdminTransaction> = [
  { title: '时间', key: 'created_at', minWidth: 170, render: (row) => formatDate(row.created_at) },
  { title: '用户', key: 'username', minWidth: 120, render: (row) => row.username || row.user_id.slice(0, 8) },
  {
    title: '变动', key: 'amount', width: 90,
    render: (row) => h('strong', { class: row.amount > 0 ? 'amount-positive' : 'amount-negative' }, `${row.amount > 0 ? '+' : ''}${row.amount}`),
  },
  { title: '余额', key: 'balance_after', width: 90 },
  { title: '原因', key: 'reason', minWidth: 220, ellipsis: { tooltip: true } },
]

onMounted(() => {
  void refreshAll()
})
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Billing</p>
        <h1>计费管理</h1>
        <span>生成兑换码、调整用户余额并检查灵感丝线流水。</span>
      </div>
      <NButton :loading="codesLoading || usersLoading || transactionsLoading" @click="refreshAll">
        <template #icon><RefreshCw :size="15" /></template>刷新全部
      </NButton>
    </header>

    <NCard size="small" class="billing-card">
      <template #header><span class="card-title"><Ticket :size="17" />兑换码管理</span></template>
      <template #header-extra>
        <NRadioGroup :value="codesFilter" size="small" @update:value="changeCodesFilter">
          <NRadioButton value="all">全部</NRadioButton>
          <NRadioButton value="unused">未使用</NRadioButton>
          <NRadioButton value="used">已使用</NRadioButton>
        </NRadioGroup>
      </template>

      <NForm ref="generateFormRef" :model="generateForm" :rules="generateRules" label-placement="top" class="generate-form">
        <NFormItem label="数量" path="count"><NInputNumber v-model:value="generateForm.count" :min="1" :max="1000" /></NFormItem>
        <NFormItem label="面额" path="credits"><NInputNumber v-model:value="generateForm.credits" :min="1" /></NFormItem>
        <NFormItem label="前缀"><NInput v-model:value="generateForm.prefix" maxlength="8" /></NFormItem>
        <NButton type="primary" :loading="generating" class="form-action" @click="generateCodes">批量生成</NButton>
      </NForm>

      <div v-if="generateResult.length > 0" class="generated-result">
        <div class="generated-result-head"><span>本次生成 {{ generateResult.length }} 个兑换码</span><NButton size="tiny" @click="copyGeneratedCodes"><template #icon><Copy :size="14" /></template>复制全部</NButton></div>
        <NInput type="textarea" :value="generateResult.join('\n')" readonly :autosize="{ minRows: 4, maxRows: 8 }" />
      </div>

      <NSpin :show="codesLoading">
        <NEmpty v-if="!codesLoading && codes.length === 0" description="当前筛选下没有兑换码" class="card-empty" />
        <NDataTable v-else :columns="codeColumns" :data="codes" :row-key="(row: RedemptionCodeItem) => row.id" size="small" :single-line="false" :scroll-x="850" :max-height="420" />
      </NSpin>
    </NCard>

    <NCard size="small" class="billing-card">
      <template #header><span class="card-title"><Wallet :size="17" />用户余额调整</span></template>
      <NSpin :show="usersLoading">
        <NForm ref="adjustFormRef" :model="adjustForm" :rules="adjustRules" label-placement="top" class="adjust-form">
          <NFormItem label="用户" path="user_id"><NSelect v-model:value="adjustForm.user_id" :options="userOptions" filterable /></NFormItem>
          <NFormItem label="调整数量" path="amount"><NInputNumber v-model:value="adjustForm.amount" /></NFormItem>
          <NFormItem label="原因"><NInput v-model:value="adjustForm.reason" maxlength="256" placeholder="可选" /></NFormItem>
          <NButton type="primary" :loading="adjusting" class="form-action" @click="adjustCredits">确认调整</NButton>
        </NForm>
      </NSpin>
    </NCard>

    <NCard size="small" class="billing-card">
      <template #header><span class="card-title"><ArrowRightLeft :size="17" />消费记录</span></template>
      <template #header-extra>
        <NSelect :value="transactionUserId || ''" :options="transactionUserOptions" filterable class="transaction-filter" @update:value="changeTransactionUser" />
      </template>
      <NSpin :show="transactionsLoading">
        <NEmpty v-if="!transactionsLoading && transactions.length === 0" description="当前页没有消费记录" class="card-empty" />
        <NDataTable v-else :columns="transactionColumns" :data="transactions" :row-key="(row: AdminTransaction) => row.id" size="small" :single-line="false" :scroll-x="760" />
      </NSpin>
      <NPagination
        v-if="transactions.length > 0 || transactionPage > 1"
        :page="transactionPage"
        :page-count="transactionPageCount"
        :page-slot="5"
        class="transaction-pagination"
        @update:page="changeTransactionPage"
      />
    </NCard>
  </section>
</template>

<style scoped>
.billing-card + .billing-card { margin-top: 18px; }
.card-title { display: inline-flex; align-items: center; gap: 8px; }
.generate-form { display: grid; grid-template-columns: 120px 140px 160px auto; gap: 0 12px; align-items: end; }
.adjust-form { display: grid; grid-template-columns: minmax(220px, .8fr) 150px minmax(220px, 1fr) auto; gap: 0 12px; align-items: end; }
.form-action { margin-bottom: 24px; }
.generated-result { margin-bottom: 16px; }
.generated-result-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; color: var(--text-secondary); font-size: 12px; }
.code-cell { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.code-value { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-empty { padding: 48px 0; }
.transaction-filter { width: 220px; }
.transaction-pagination { justify-content: flex-end; margin-top: 14px; }
@media (max-width: 900px) { .generate-form, .adjust-form { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .generate-form, .adjust-form { grid-template-columns: 1fr; } .form-action { margin-bottom: 10px; } .transaction-filter { width: 160px; } }
</style>
