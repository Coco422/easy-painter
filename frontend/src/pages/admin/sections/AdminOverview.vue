<script setup lang="ts">
import { computed, h, onActivated, onBeforeUnmount, onDeactivated, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NRadioButton,
  NRadioGroup,
  NSpin,
  NStatistic,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { Activity, RefreshCw } from 'lucide-vue-next'

import { ApiError, adminFetchHealth, adminFetchOverview } from '@/lib/api'
import type { AdminHealth, AdminMetricItem, AdminOverview } from '@/lib/types'

type WindowValue = '24h' | '7d' | '30d'
type HealthRow = { key: string; label: string; status: string; detail: string }

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const overview = ref<AdminOverview | null>(null)
const health = ref<AdminHealth | null>(null)
const windowValue = ref<WindowValue>('24h')
const loading = ref(false)
const refreshing = ref(false)
let refreshTimer: number | undefined

const windowLabel = computed(() => ({ '24h': '近 24 小时', '7d': '近 7 天', '30d': '近 30 天' })[windowValue.value])
const liveJobs = computed(() => (overview.value?.queued_jobs ?? 0) + (overview.value?.processing_jobs ?? 0))
const healthRows = computed<HealthRow[]>(() => {
  if (!health.value) return []
  const labels: Record<string, string> = {
    database: 'PostgreSQL',
    schema: 'Flyway Schema',
    redis: 'Redis',
    minio: 'MinIO',
    dispatcher: 'Dispatcher',
    worker: 'Celery Worker',
    queue: 'Generation 队列',
    outbox: 'Transactional Outbox',
    smtp: 'SMTP',
    media_cleanup: '媒体清理',
  }
  return Object.entries(health.value.components)
    .filter(([key]) => key !== 'providers')
    .map(([key, item]) => ({
      key,
      label: labels[key] ?? key,
      status: item.status,
      detail: healthDetail(key, item),
    }))
})

function healthDetail(key: string, item: Record<string, unknown>) {
  if (key === 'schema') return `v${item.version ?? '-'} / 期望 v${item.expected ?? '-'}`
  if (key === 'dispatcher') return item.ttl === undefined ? '-' : `心跳 TTL ${item.ttl}s`
  if (key === 'worker') return `${item.count ?? 0} 个 Worker`
  if (key === 'queue') return `队列深度 ${item.depth ?? 0}`
  if (key === 'outbox') return `${item.pending ?? 0} 条待投递 · 最老等待 ${formatDuration(Number(item.oldest_wait_seconds ?? 0))}`
  if (key === 'smtp') return item.status === 'configured' ? '已配置发送通道' : '未配置，不影响图片生成'
  if (key === 'media_cleanup') {
    return `${item.pending ?? 0} 条待清理 · ${item.failed_retries ?? 0} 条重试 · 社区待迁移 ${item.community_assets_pending_migration ?? 0}`
  }
  if (item.detail) return String(item.detail)
  return '正常'
}

function formatDuration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds)) return '-'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function statusLabel(status: string) {
  return ({ ok: '正常', configured: '已配置', not_configured: '未配置', degraded: '降级', unavailable: '不可用' } as Record<string, string>)[status] ?? status
}

function statusType(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'ok' || status === 'configured') return 'success'
  if (status === 'degraded' || status === 'not_configured') return 'warning'
  if (status === 'unavailable') return 'error'
  return 'default'
}

function handleError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) {
    message.error('管理员密钥已过期，请重新验证。')
    emit('auth-expired')
    return
  }
  message.error(error instanceof Error ? error.message : fallback)
}

async function loadData(silent = false) {
  if (refreshing.value) return
  refreshing.value = true
  if (!silent && !overview.value) loading.value = true
  const [overviewResult, healthResult] = await Promise.allSettled([
    adminFetchOverview(windowValue.value),
    adminFetchHealth(),
  ])
  if (overviewResult.status === 'fulfilled') overview.value = overviewResult.value
  else handleError(overviewResult.reason, '运营总览加载失败。')
  if (healthResult.status === 'fulfilled') health.value = healthResult.value
  else handleError(healthResult.reason, '依赖健康状态加载失败。')
  loading.value = false
  refreshing.value = false
}

function changeWindow(value: WindowValue) {
  windowValue.value = value
  void loadData()
}

function startAutoRefresh() {
  if (refreshTimer !== undefined) return
  refreshTimer = window.setInterval(() => void loadData(true), 30_000)
}

function stopAutoRefresh() {
  if (refreshTimer === undefined) return
  window.clearInterval(refreshTimer)
  refreshTimer = undefined
}

const metricColumns: DataTableColumns<AdminMetricItem> = [
  { title: '名称', key: 'label', minWidth: 180, ellipsis: { tooltip: true } },
  { title: '任务', key: 'total', width: 80 },
  { title: '成功', key: 'succeeded', width: 80 },
  { title: '失败', key: 'failed', width: 80 },
  { title: '已结算消耗', key: 'credits', width: 110, render: (row) => `${row.credits} 丝` },
  {
    title: '成功率', key: 'success_rate', width: 90,
    render: (row) => {
      const terminal = row.succeeded + row.failed
      return terminal ? `${(row.succeeded / terminal * 100).toFixed(1)}%` : '-'
    },
  },
]

const healthColumns: DataTableColumns<HealthRow> = [
  { title: '依赖', key: 'label', minWidth: 160 },
  {
    title: '状态', key: 'status', width: 100,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: statusType(row.status) }, { default: () => statusLabel(row.status) }),
  },
  { title: '详情', key: 'detail', minWidth: 220 },
]

onActivated(() => {
  void loadData(Boolean(overview.value))
  startAutoRefresh()
})
onDeactivated(stopAutoRefresh)
onBeforeUnmount(stopAutoRefresh)
</script>

<template>
  <section class="admin-section-view overview-view">
    <header class="section-header">
      <div>
        <p class="section-kicker">Operations</p>
        <h1>运营总览</h1>
        <span>任务交付、账务退款、队列积压和核心依赖的统一视图，每 30 秒自动刷新。</span>
      </div>
      <div class="overview-actions">
        <NRadioGroup :value="windowValue" size="small" @update:value="changeWindow">
          <NRadioButton value="24h">24h</NRadioButton>
          <NRadioButton value="7d">7d</NRadioButton>
          <NRadioButton value="30d">30d</NRadioButton>
        </NRadioGroup>
        <NButton :loading="refreshing" @click="loadData(false)">
          <template #icon><RefreshCw :size="15" /></template>
          刷新
        </NButton>
      </div>
    </header>

    <NSpin :show="loading">
      <NEmpty v-if="!loading && !overview" description="总览暂不可用" class="overview-empty" />
      <template v-else-if="overview">
        <div class="overview-kpis">
          <NCard size="small"><NStatistic label="任务量" :value="overview.total_jobs"><template #suffix><small>{{ windowLabel }}</small></template></NStatistic></NCard>
          <NCard size="small"><NStatistic label="交付成功率" :value="overview.success_rate" suffix="%" /></NCard>
          <NCard size="small"><NStatistic label="进行中" :value="liveJobs"><template #suffix><small>{{ overview.queued_jobs }} 排队 / {{ overview.processing_jobs }} 执行</small></template></NStatistic></NCard>
          <NCard size="small"><NStatistic label="P50 / P95" :value="formatDuration(overview.p50_seconds)"><template #suffix><small>{{ formatDuration(overview.p95_seconds) }}</small></template></NStatistic></NCard>
          <NCard size="small"><NStatistic label="退款" :value="overview.refunded_credits"><template #suffix><small>{{ overview.refund_count }} 笔</small></template></NStatistic></NCard>
          <NCard size="small"><NStatistic label="活跃用户" :value="overview.active_users" /></NCard>
        </div>

        <div class="overview-grid">
          <NCard size="small" title="模型表现">
            <NEmpty v-if="overview.models.length === 0" description="当前窗口暂无任务" class="compact-empty" />
            <NDataTable v-else :columns="metricColumns" :data="overview.models" :row-key="(row: AdminMetricItem) => row.label" size="small" :single-line="false" :scroll-x="620" />
          </NCard>
          <NCard size="small" title="渠道表现">
            <NEmpty v-if="overview.providers.length === 0" description="当前窗口暂无渠道记录" class="compact-empty" />
            <NDataTable v-else :columns="metricColumns" :data="overview.providers" :row-key="(row: AdminMetricItem) => row.label" size="small" :single-line="false" :scroll-x="620" />
          </NCard>
        </div>

        <div class="overview-grid overview-grid--lower">
          <NCard size="small">
            <template #header><span class="overview-card-title"><Activity :size="16" />失败原因 Top</span></template>
            <NEmpty v-if="overview.top_errors.length === 0" description="当前窗口没有失败任务" class="compact-empty" />
            <ol v-else class="error-ranking">
              <li v-for="item in overview.top_errors" :key="item.message">
                <span>{{ item.message }}</span><strong>{{ item.count }}</strong>
              </li>
            </ol>
          </NCard>
          <NCard size="small" title="依赖健康">
            <div class="health-summary">
              <NTag :type="statusType(health?.status ?? 'unavailable')" :bordered="false">
                {{ health?.status === 'ok' ? '所有核心链路正常' : '存在降级或不可用依赖' }}
              </NTag>
              <span>SMTP 未配置仅影响邮件功能，不影响生成 readiness。</span>
            </div>
            <NDataTable :columns="healthColumns" :data="healthRows" :row-key="(row: HealthRow) => row.key" size="small" :single-line="false" :scroll-x="500" />
          </NCard>
        </div>
      </template>
    </NSpin>
  </section>
</template>

<style scoped>
.overview-actions { display: flex; align-items: center; gap: 10px; }
.overview-kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.overview-kpis small { margin-left: 7px; color: var(--text-muted); font-size: 10px; font-weight: 500; }
.overview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.overview-grid + .overview-grid { margin-top: 16px; }
.overview-card-title { display: inline-flex; align-items: center; gap: 8px; }
.overview-empty { padding: 96px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); }
.compact-empty { padding: 42px 0; }
.error-ranking { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.error-ranking li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; padding: 11px 0; border-bottom: 1px solid var(--border); }
.error-ranking li:last-child { border-bottom: 0; }
.error-ranking span { overflow: hidden; color: var(--text-secondary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.error-ranking strong { color: var(--error); font: 600 12px/1.5 var(--font-mono); }
.health-summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; color: var(--text-muted); font-size: 11px; }
@media (max-width: 1180px) { .overview-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 820px) { .overview-grid { grid-template-columns: 1fr; } .overview-actions { align-items: stretch; flex-direction: column; } }
@media (max-width: 560px) { .overview-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } .health-summary { align-items: flex-start; flex-direction: column; } }
</style>
