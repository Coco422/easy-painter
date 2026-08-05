<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NImage,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
  type DataTableRowKey,
} from 'naive-ui'
import { Eye, RefreshCw, Trash2 } from 'lucide-vue-next'

import { ApiError, adminBatchDeleteJobs, adminDeleteJob, adminFetchJobs } from '@/lib/api'
import type { AdminJobItem } from '@/lib/types'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const dialog = useDialog()

const jobs = ref<AdminJobItem[]>([])
const loading = ref(false)
const batchDeleting = ref(false)
const statusFilter = ref('')
const selectedRowKeys = ref<DataTableRowKey[]>([])
const selectedJob = ref<AdminJobItem | null>(null)

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '排队中', value: 'queued' },
  { label: '生成中', value: 'processing' },
  { label: '成功', value: 'succeeded' },
  { label: '失败', value: 'failed' },
]

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

function formatDuration(start: string | null, end: string | null) {
  if (!start || !end) return '-'
  const milliseconds = new Date(end).getTime() - new Date(start).getTime()
  if (milliseconds < 1000) return `${milliseconds}ms`
  return `${(milliseconds / 1000).toFixed(1)}s`
}

function formatMeta(meta: Record<string, unknown> | null) {
  return meta ? JSON.stringify(meta, null, 2) : '-'
}

function statusLabel(status: string) {
  return ({ queued: '排队中', processing: '生成中', succeeded: '成功', failed: '失败' } as Record<string, string>)[status] ?? status
}

function statusTagType(status: string): 'default' | 'info' | 'success' | 'error' {
  if (status === 'processing') return 'info'
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'error'
  return 'default'
}

function billingStatusLabel(status: string) {
  return ({ not_charged: '未扣费', reserved: '已预扣', settled: '已结算', refunded: '已退款' } as Record<string, string>)[status] ?? status
}

function outboxStatusLabel(status: string | null) {
  if (!status) return '无记录'
  return ({ pending: '待投递', published: '已投递', discarded: '已丢弃' } as Record<string, string>)[status] ?? status
}

async function loadJobs() {
  loading.value = true
  try {
    jobs.value = await adminFetchJobs(statusFilter.value || undefined)
    selectedRowKeys.value = []
  } catch (error) {
    handleError(error, '任务列表加载失败。')
  } finally {
    loading.value = false
  }
}

function viewJob(job: AdminJobItem) {
  selectedJob.value = job
}

function deleteJob(job: AdminJobItem) {
  dialog.warning({
    title: '删除任务',
    content: '确定删除这个任务吗？关联的生成图片和任务级参考图也会被删除。',
    positiveText: '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      try {
        await adminDeleteJob(job.job_id)
        jobs.value = jobs.value.filter((item) => item.job_id !== job.job_id)
        selectedRowKeys.value = selectedRowKeys.value.filter((key) => key !== job.job_id)
        if (selectedJob.value?.job_id === job.job_id) selectedJob.value = null
        message.success('任务已删除。')
      } catch (error) {
        handleError(error, '任务删除失败。')
      }
    },
  })
}

function deleteSelectedJobs() {
  const ids = selectedRowKeys.value.map(String)
  if (ids.length === 0) return
  dialog.warning({
    title: '批量删除任务',
    content: `确定删除选中的 ${ids.length} 个任务吗？关联图片也会一并删除。`,
    positiveText: '批量删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    async onPositiveClick() {
      batchDeleting.value = true
      try {
        const result = await adminBatchDeleteJobs(ids)
        await loadJobs()
        if (result.failed.length > 0) {
          message.warning(`已删除 ${result.deleted} 个任务，${result.failed.length} 个任务未能删除。`)
        } else {
          message.success(`已删除 ${result.deleted} 个任务。`)
        }
      } catch (error) {
        handleError(error, '批量删除失败。')
      } finally {
        batchDeleting.value = false
      }
    },
  })
}

const columns: DataTableColumns<AdminJobItem> = [
  { type: 'selection', fixed: 'left' },
  { title: 'ID', key: 'job_id', width: 92, fixed: 'left', render: (row) => h('code', { class: 'job-id' }, row.job_id.slice(0, 8)) },
  {
    title: '状态', key: 'status', width: 95,
    render: (row) => h(NTag, { size: 'small', type: statusTagType(row.status), bordered: false }, { default: () => statusLabel(row.status) }),
  },
  { title: '提示词', key: 'prompt', minWidth: 260, ellipsis: { tooltip: true } },
  { title: '模型', key: 'model', minWidth: 170, ellipsis: { tooltip: true }, render: (row) => row.model_label || row.model },
  { title: '消费', key: 'credit_cost', width: 85, render: (row) => `${row.credit_cost} 丝` },
  { title: '账务', key: 'billing_status', width: 95, render: (row) => billingStatusLabel(row.billing_status) },
  { title: '用户', key: 'username', width: 110, render: (row) => row.username || '-' },
  { title: '耗时', key: 'duration', width: 90, render: (row) => formatDuration(row.started_at, row.finished_at) },
  { title: '创建时间', key: 'created_at', minWidth: 170, render: (row) => formatDate(row.created_at) },
  {
    title: '操作', key: 'actions', width: 150, fixed: 'right',
    render(row) {
      return h(NSpace, { size: 6, wrap: false }, { default: () => [
        h(NButton, { size: 'tiny', onClick: () => viewJob(row) }, { icon: () => h(Eye, { size: 14 }), default: () => '详情' }),
        h(NButton, { size: 'tiny', type: 'error', ghost: true, onClick: () => deleteJob(row) }, { default: () => '删除' }),
      ] })
    },
  },
]

onMounted(loadJobs)
</script>

<template>
  <section class="admin-section-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Jobs</p>
        <h1>任务管理</h1>
        <span>检查生成状态、上游返回信息并清理任务产物。</span>
      </div>
      <NButton :loading="loading" @click="loadJobs"><template #icon><RefreshCw :size="15" /></template>刷新</NButton>
    </header>

    <div class="table-toolbar">
      <NSelect v-model:value="statusFilter" :options="statusOptions" class="status-select" @update:value="loadJobs" />
      <NButton v-if="selectedRowKeys.length > 0" type="error" ghost :loading="batchDeleting" @click="deleteSelectedJobs">
        <template #icon><Trash2 :size="15" /></template>
        删除选中（{{ selectedRowKeys.length }}）
      </NButton>
    </div>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && jobs.length === 0" description="当前筛选下没有任务" class="section-empty" />
      <NDataTable
        v-else
        v-model:checked-row-keys="selectedRowKeys"
        :columns="columns"
        :data="jobs"
        :row-key="(row: AdminJobItem) => row.job_id"
        size="small"
        :single-line="false"
        :scroll-x="1450"
        :max-height="680"
      />
    </NSpin>

    <NDrawer :show="Boolean(selectedJob)" width="min(560px, 100vw)" placement="right" @update:show="(show) => { if (!show) selectedJob = null }">
      <NDrawerContent v-if="selectedJob" title="任务详情" closable>
        <NDescriptions label-placement="left" :column="1" bordered size="small">
          <NDescriptionsItem label="任务 ID"><code>{{ selectedJob.job_id }}</code></NDescriptionsItem>
          <NDescriptionsItem label="状态"><NTag :type="statusTagType(selectedJob.status)" size="small" :bordered="false">{{ statusLabel(selectedJob.status) }}</NTag></NDescriptionsItem>
          <NDescriptionsItem label="模型">{{ selectedJob.model_label || selectedJob.model }}</NDescriptionsItem>
          <NDescriptionsItem label="模型 ID"><code>{{ selectedJob.model }}</code></NDescriptionsItem>
          <NDescriptionsItem label="渠道快照">{{ selectedJob.provider_name || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="单次价格">{{ selectedJob.credit_cost }} 丝</NDescriptionsItem>
          <NDescriptionsItem label="账务状态">{{ billingStatusLabel(selectedJob.billing_status) }}</NDescriptionsItem>
          <NDescriptionsItem label="退款时间">{{ formatDate(selectedJob.refunded_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="尺寸">{{ selectedJob.size }}</NDescriptionsItem>
          <NDescriptionsItem label="宽高比">{{ selectedJob.aspect_ratio }}</NDescriptionsItem>
          <NDescriptionsItem label="用户">{{ selectedJob.username || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="参考图">{{ selectedJob.reference_image_filename || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="创建时间">{{ formatDate(selectedJob.created_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="开始时间">{{ formatDate(selectedJob.started_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="完成时间">{{ formatDate(selectedJob.finished_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="耗时">{{ formatDuration(selectedJob.started_at, selectedJob.finished_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="执行领取">{{ selectedJob.execution_claimed ? 'Worker 已领取' : '未被领取 / 已释放' }}</NDescriptionsItem>
          <NDescriptionsItem label="执行租约">{{ formatDate(selectedJob.lease_expires_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="Outbox">{{ outboxStatusLabel(selectedJob.outbox_status) }}</NDescriptionsItem>
          <NDescriptionsItem label="投递尝试">{{ selectedJob.outbox_attempts }}</NDescriptionsItem>
          <NDescriptionsItem label="投递时间">{{ formatDate(selectedJob.outbox_published_at) }}</NDescriptionsItem>
        </NDescriptions>

        <div class="detail-block"><h3>提示词</h3><p>{{ selectedJob.prompt }}</p></div>
        <div v-if="selectedJob.revised_prompt" class="detail-block"><h3>修订提示词</h3><p>{{ selectedJob.revised_prompt }}</p></div>
        <div v-if="selectedJob.error_message" class="detail-block error"><h3>错误信息</h3><p>{{ selectedJob.error_message }}</p></div>
        <div v-if="selectedJob.outbox_last_error" class="detail-block error"><h3>Outbox 最近错误</h3><p>{{ selectedJob.outbox_last_error }}</p></div>
        <div v-if="selectedJob.provider_job_meta" class="detail-block"><h3>上游元数据</h3><pre>{{ formatMeta(selectedJob.provider_job_meta) }}</pre></div>
        <div v-if="selectedJob.image_url" class="detail-block"><h3>生成结果</h3><NImage :src="selectedJob.image_url" object-fit="contain" /></div>
      </NDrawerContent>
    </NDrawer>
  </section>
</template>

<style scoped>
.table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.status-select { width: 180px; }
.section-empty { padding: 72px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.detail-block { margin-top: 22px; }
.detail-block h3 { margin: 0 0 8px; color: var(--text-muted); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
.detail-block p { margin: 0; color: var(--text-secondary); line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.detail-block pre { overflow-x: auto; margin: 0; padding: 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-elevated); color: var(--text-secondary); font: 12px/1.6 var(--font-mono); }
.detail-block.error p { color: var(--error); }
code { font-family: var(--font-mono); }
@media (max-width: 560px) { .table-toolbar { align-items: stretch; flex-direction: column; } .status-select { width: 100%; } }
</style>
