<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, GitBranch, Layers, PencilLine, Plus, Sparkles } from 'lucide-vue-next'
import ProtectedImage from './ProtectedImage.vue'
import MediaExpiry from './MediaExpiry.vue'
import GenerationWaiting from './GenerationWaiting.vue'
import { useGenerationQuips } from '@/composables/useGenerationQuips'
import { creationResultBatches, creationVersionRows, type CreationHistory } from '@/lib/creation-versions'
import { mediaAvailable } from '@/lib/media-state'
import { useMediaClock } from '@/composables/useMediaClock'
import type { JobDetailResponse } from '@/lib/types'

const props = defineProps<{
  jobs: JobDetailResponse[]
  membership: Record<string, string>
  parents: CreationHistory['parents']
  selectedId: string
  drafting?: boolean
  canStartNew?: boolean
  busy: boolean
  pending: boolean
  editModel: string
  editCost: number
  editSize: string
  maxLength: number
  canvases: { id: string; title: string }[]
}>()
const emit = defineEmits<{
  select: [id: string]
  revise: [instruction: string]
  confirm: []
  canvas: [job: JobDetailResponse, target: string]
  details: [job: JobDetailResponse]
  gallery: [job: JobDetailResponse]
  refresh: [job: JobDetailResponse]
  retry: [job: JobDetailResponse]
  dismiss: [id: string]
  new: []
}>()
const now = useMediaClock()
const quips = useGenerationQuips(computed(() => props.jobs))
const instruction = ref('')
const target = ref('')
const rows = computed(() => creationVersionRows(props.jobs, props.parents, props.membership))
const batches = computed(() => creationResultBatches(rows.value).map(batch => {
  const jobs = batch.candidates.flatMap(candidate => candidate.rows.map(row => row.job))
  return { ...batch, jobs, pending: jobs.filter(job => job.status === 'queued' || job.status === 'processing').length }
}).reverse())
const selected = computed(() => rows.value.find(row => row.job.job_id === props.selectedId) ?? rows.value[rows.value.length - 1])
const currentBatch = computed(() => batches.value.find(batch => batch.id === selected.value?.batchId))
const hasPeers = computed(() => (currentBatch.value?.candidates.length ?? 0) > 1)
const batchTitle = computed(() => `第 ${currentBatch.value?.number} ${hasPeers.value ? '批' : '次绘图'}`)
const summary = computed(() => {
  const jobs = currentBatch.value?.jobs ?? []
  const succeeded = jobs.filter(job => job.status === 'succeeded').length
  const failed = jobs.filter(job => job.status === 'failed').length
  const amount = (status: string) => jobs.filter(job => job.billing_status === status).reduce((sum, job) => sum + job.credit_cost, 0)
  return { total: jobs.length, succeeded, failed, finished: succeeded + failed,
    reserved: amount('reserved'), settled: amount('settled'), refunded: amount('refunded') }
})
const branch = computed(() => rows.value.filter(row => row.rootId === selected.value?.rootId))
const hasBranch = computed(() => branch.value.length > 1 || !!selected.value?.parentId)
const sourceLabel = computed(() => selected.value?.parentNumber ? `基于 V${selected.value.parentNumber} 修改` : selected.value?.parentId ? '来自较早版本' : hasPeers.value ? '独立候选图' : '')
const resultLabel = computed(() => !hasPeers.value && hasBranch.value && !selected.value?.parentId ? '原图 · V1' : selected.value?.label)
const usable = computed(() => !!selected.value && selected.value.job.status === 'succeeded' && mediaAvailable(selected.value.job.media_state ?? 'none', selected.value.job.media_expires_at, now.value))
const statusLabel = { queued: '排队中', processing: '生成中', succeeded: '已完成', failed: '失败' }
const showEditor = ref(false)
const batchPending = computed(() => currentBatch.value?.pending ?? 0)
const editSuffix = computed(() => editCount.value ? ` · ${editCount.value} 次修改` : '')
const raceLabel = computed(() => {
  if (batchPending.value) return `已生成 ${summary.value.succeeded} / ${summary.value.total} 张${editSuffix.value} · ${batchPending.value} 张生成中`
  if (summary.value.failed) return `${summary.value.failed} 张失败${editSuffix.value} · ${summary.value.refunded ? `已退回 ${summary.value.refunded} 丝` : '见下方说明'}`
  return `生成已结束${editSuffix.value}`
})
const editCount = computed(() => Math.max(0, summary.value.total - (currentBatch.value?.candidates.length ?? 0)))
const overviewSubtitle = computed(() => hasPeers.value ? `${currentBatch.value?.candidates.length} 张候选图` : '单张作品')
const showVersionTitle = computed(() => !props.drafting && Boolean(hasPeers.value || hasBranch.value || selected.value?.parentId))
watch([() => props.selectedId, () => props.drafting], () => { showEditor.value = false; instruction.value = '' })
function openEditor() { showEditor.value = true }
function billingLabel(job: JobDetailResponse) {
  const labels: Record<string, string> = { reserved: '已预扣', settled: '已结算', refunded: '已全额退回', not_charged: '未扣费' }
  const label = labels[job.billing_status] ?? '计费待确认'
  return job.billing_status === 'not_charged' ? label : `${label} ${job.credit_cost} 丝`
}
function stageText(job: JobDetailResponse) {
  if (job.status === 'queued') return '排队中'
  if (job.status === 'processing') return '正在绘制'
  return '已完成'
}
</script>

<template>
  <section v-if="selected" class="version-workspace" aria-label="绘图结果">
    <nav class="drawing-navigation" aria-label="最近绘图">
      <span class="drawing-navigation-label">最近绘图</span>
      <div class="drawing-tabs" role="group" aria-label="切换绘图批次">
        <button v-if="drafting" type="button" class="drawing-tab drawing-tab--draft" aria-pressed="true"><Plus :size="14" aria-hidden="true" /><strong>新的绘图</strong><small>待创作</small></button>
        <button v-for="batch in batches" :key="batch.id" type="button" class="drawing-tab" :class="{ 'drawing-tab--live': batch.pending }" :aria-pressed="!drafting && currentBatch?.id === batch.id" :aria-label="`查看第 ${batch.number} ${batch.candidates.length > 1 ? '批绘图' : '次绘图'}，${batch.candidates.length} 张${batch.candidates.length > 1 ? '候选图' : '图片'}${batch.pending ? `，${batch.pending} 张生成中` : ''}`" :title="batch.candidates[0]?.job.prompt" @click="emit('select', batch.candidates[0]!.job.job_id)">
          <span v-if="batch.pending" class="drawing-pending-dot" aria-hidden="true" />
          <span class="drawing-tab-number">{{ batch.number }}</span>
        </button>
      </div>
      <router-link class="drawing-navigation-all" to="/history">全部历史</router-link>
    </nav>

    <template v-if="!drafting && currentBatch">
    <div v-if="showVersionTitle" class="version-title"><strong>{{ batchTitle }} · {{ resultLabel }} <span v-if="sourceLabel">{{ sourceLabel }}</span></strong><span>{{ statusLabel[selected.job.status] }}</span></div>
    <section class="batch-overview" :aria-label="`${batchTitle}进度与计费`">
      <p v-if="!showVersionTitle" class="batch-overview-heading"><span>{{ batchTitle }} · {{ overviewSubtitle }}</span><span v-if="editCount"> · {{ editCount }} 次修改</span></p>
      <div class="batch-overview-status" role="status" :class="{ live: batchPending, failed: !batchPending && summary.failed }">
        <span class="status-dot" aria-hidden="true" />
        {{ raceLabel }}
      </div>
      <div class="batch-progress" :class="{ 'batch-progress--failed': summary.failed && !batchPending, 'batch-progress--live': batchPending }" role="progressbar" :aria-label="`${batchTitle}任务完成进度`" aria-valuemin="0" :aria-valuemax="summary.total" :aria-valuenow="summary.finished" :aria-valuetext="`${summary.finished} / ${summary.total} 个任务已结束，${summary.succeeded} 张成功，${summary.failed} 张失败`"><span :style="{ width: `${summary.finished / summary.total * 100}%` }" /></div>
      <p class="batch-parameters">
        <span class="batch-parameters-prompt" :title="currentBatch.candidates[0]?.job.prompt">{{ currentBatch.candidates[0]?.job.prompt }}</span>
        <span class="batch-parameters-meta">{{ currentBatch.candidates[0]?.job.model_label || currentBatch.candidates[0]?.job.model }} · {{ currentBatch.candidates[0]?.job.size }}</span>
      </p>
      <div class="batch-billing">
        <span v-if="summary.reserved">已预扣 {{ summary.reserved }} 丝</span>
        <span v-if="summary.settled">已结算 {{ summary.settled }} 丝</span>
        <span v-if="summary.refunded" class="batch-billing-refund">已退回 {{ summary.refunded }} 丝</span>
        <span v-if="!summary.reserved && !summary.settled && !summary.refunded">本批未扣费</span>
      </div>
    </section>

    <div class="batch-results">
      <section v-if="hasPeers" class="candidate-batch" :aria-label="`第 ${currentBatch.number} 批候选图`">
        <div class="candidate-grid" role="group" :aria-label="`选择第 ${currentBatch.number} 批候选图`">
          <button v-for="candidate in currentBatch.candidates" :key="candidate.id" type="button" class="candidate-card" :class="{ 'candidate-card--live': candidate.job.status === 'queued' || candidate.job.status === 'processing' }" :aria-pressed="selected.rootId === candidate.id" :aria-label="`第 ${currentBatch.number} 批，${candidate.label}，${statusLabel[candidate.job.status]}`" @click="emit('select', candidate.job.job_id)">
            <ProtectedImage v-if="candidate.job.status === 'succeeded'" :src="candidate.job.thumbnail_url || candidate.job.image_url" :state="candidate.job.media_state" :expires-at="candidate.job.media_expires_at" :alt="candidate.label" @invalid="emit('refresh', candidate.job)" />
            <GenerationWaiting v-else-if="candidate.job.status === 'queued' || candidate.job.status === 'processing'" class="candidate-waiting" :status="candidate.job.status" :quip="quips.get(candidate.job.job_id)!" compact />
            <span v-else class="candidate-placeholder" role="status">{{ statusLabel[candidate.job.status] }}</span>
            <span class="candidate-badge" :class="{ 'candidate-badge--refunded': candidate.job.billing_status === 'refunded' }">{{ candidate.rows.some(row => row.parentId) ? `${candidate.rows.filter(row => row.parentId).length} 个修改` : billingLabel(candidate.job) }}</span>
            <span class="candidate-index" aria-hidden="true">{{ candidate.rows[0]!.candidateNumber }}</span>
          </button>
        </div>
      </section>

      <div class="result-stage">
        <div class="result-frame">
          <div v-if="showVersionTitle" class="result-frame-top">
            <span class="result-chip">{{ batchTitle }} · {{ resultLabel }}</span>
            <span class="result-chip-state" :class="{ live: selected.job.status === 'queued' || selected.job.status === 'processing' }">{{ stageText(selected.job) }}</span>
          </div>
          <div class="version-preview">
            <ProtectedImage v-if="selected.job.status === 'succeeded'" :key="selected.job.job_id" :src="selected.job.image_url" :state="selected.job.media_state" :expires-at="selected.job.media_expires_at" :alt="hasPeers || hasBranch ? `${batchTitle} · ${resultLabel}` : '生成结果'" eager preview @invalid="emit('refresh', selected.job)" />
            <GenerationWaiting v-else-if="selected.job.status === 'queued' || selected.job.status === 'processing'" :key="selected.job.job_id" :status="selected.job.status" :quip="quips.get(selected.job.job_id)!" :hint="selected.job.error_message" />
            <div v-else class="version-placeholder" role="status"><strong>{{ statusLabel[selected.job.status] }}</strong><span>{{ selected.job.error_message || '这张图片生成失败。' }}</span></div>
          </div>
          <div v-if="selected.job.status === 'succeeded'" class="result-frame-foot">
            <MediaExpiry :state="selected.job.media_state ?? 'none'" :expires-at="selected.job.media_expires_at" :permanent="selected.job.retention_kind === 'permanent'" />
            <span class="result-frame-params">{{ selected.job.model_label || selected.job.model }} · {{ selected.job.size }} · {{ billingLabel(selected.job) }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-if="selected.job.status === 'failed'" class="version-failure" role="alert"><p>{{ selected.job.error_message || '这张图片生成失败。' }}<span v-if="selected.job.billing_status === 'refunded'"> {{ selected.job.credit_cost }} 丝已全额退回余额。</span></p><div class="version-actions"><button type="button" :disabled="busy || pending" @click="emit('retry', selected.job)">重新生成</button><button type="button" :disabled="busy" @click="emit('dismiss', selected.job.job_id)">收起这张图</button></div></div>
    <div v-else class="version-actions">
      <button type="button" class="version-primary" :disabled="!usable || busy || pending" @click="openEditor"><PencilLine :size="15" />继续修改{{ selected.parentId ? ` V${selected.number}` : '' }}</button>
      <button type="button" :disabled="!usable || busy" @click="emit('details', selected.job)">详情与下载</button>
      <button type="button" :disabled="!usable || busy" @click="emit('gallery', selected.job)">加入画廊</button>
      <span class="version-actions-spacer" />
      <div class="version-canvas-actions">
        <label><span class="sr-only">目标画布</span><select v-model="target" :disabled="busy"><option value="">新建画布</option><option v-for="canvas in canvases" :key="canvas.id" :value="canvas.id">{{ canvas.title }}</option></select></label>
        <button type="button" :disabled="!usable || busy" @click="emit('canvas', selected.job, target)"><Layers :size="15" />{{ busy ? '处理中…' : '加入画布' }}</button>
      </div>
    </div>
    <div v-if="showEditor && usable && !pending" class="version-editor">
      <label :for="`revision-${selected.job.job_id}`"><GitBranch :size="15" />{{ hasPeers ? `基于${selected.label}生成修改版，保留原图` : '描述修改内容，保留原图' }}</label>
      <textarea :id="`revision-${selected.job.job_id}`" v-model="instruction" rows="3" :maxlength="maxLength" :disabled="busy" placeholder="例如：改成蓝色配色，保留现有布局和文字" />
      <div class="version-editor-footer"><span>{{ editModel || '暂无支持改图的模型' }} · {{ editSize }} · {{ editCost }} 丝 / 次</span><button type="button" class="version-primary" :disabled="busy || !instruction.trim() || !editModel" @click="emit('revise', instruction)"><Sparkles :size="15" />{{ busy ? '正在提交…' : '生成修改版' }}</button></div>
    </div>
    <div v-if="pending" class="version-pending" role="status"><p>上次改图的提交结果尚未确认。确认会复用原请求，不会创建第二个任务。</p><button type="button" :disabled="busy" @click="emit('confirm')">确认上次改图任务</button></div>
    <template v-if="hasBranch">
    <div class="version-history-heading"><h3><GitBranch :size="16" />{{ hasPeers ? `${selected.candidateLabel}的修改分支` : '修改记录' }} <span>{{ branch.length }}</span></h3><span>可选中原图或旧版本分叉修改</span></div>
    <div class="version-history" role="group" :aria-label="hasPeers ? `选择第 ${selected.batchNumber} 批${selected.candidateLabel}的修改版本` : `选择第 ${selected.batchNumber} 次绘图的修改记录`">
      <button v-for="row in branch" :key="row.job.job_id" type="button" :aria-pressed="selected.job.job_id === row.job.job_id" :aria-label="`V${row.number}${row.parentNumber ? `，基于 V${row.parentNumber}` : row.parentId ? '，来自较早版本' : '，原图'}，${statusLabel[row.job.status]}`" @click="emit('select', row.job.job_id)">
        <ProtectedImage v-if="row.job.status === 'succeeded'" :src="row.job.thumbnail_url || row.job.image_url" :state="row.job.media_state" :expires-at="row.job.media_expires_at" :alt="`V${row.number} 缩略图`" />
        <span v-else class="version-history-placeholder">{{ statusLabel[row.job.status] }}</span>
        <strong>V{{ row.number }} <span v-if="row.parentNumber"><ArrowRight :size="11" /> V{{ row.parentNumber }}</span></strong><small>{{ row.parentNumber ? `基于 V${row.parentNumber} 修改` : row.parentId ? '来自较早版本' : '原图' }}</small>
      </button>
    </div>
    </template>
    <div class="drawing-next"><span>想画点不一样的？之前的作品会保留。</span><button type="button" class="workspace-new-drawing" :disabled="busy || canStartNew === false" @click="emit('new')"><Plus :size="15" aria-hidden="true" />新绘图</button></div>
    </template>
  </section>
</template>

<style scoped>
.version-workspace { display: grid; gap: 14px; min-width: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* ---- recent drawings rail ---- */
.drawing-navigation { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 8px 10px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg-surface); }
.drawing-navigation-label { flex: none; font-size: 11.5px; color: var(--text-muted); }
.drawing-tabs { display: flex; flex: 1; align-items: center; gap: 6px; min-width: 0; overflow-x: auto; padding: 2px; scrollbar-width: thin; }
.drawing-tab { position: relative; display: grid; place-items: center; flex: 0 0 38px; width: 38px; height: 38px; padding: 0; }
.drawing-tab strong, .drawing-tab small { display: none; }
.drawing-tab-number { font: 500 12px var(--font-mono); color: var(--text-secondary); }
.drawing-tab[aria-pressed='true'] { border-color: var(--accent); background: var(--accent-soft); }
.drawing-tab[aria-pressed='true'] .drawing-tab-number { color: var(--accent-strong); }
.drawing-tab--live { border-style: dashed; }
.drawing-tab--draft { display: flex; width: auto; flex-basis: auto; gap: 5px; padding: 0 10px; font-size: 12px; }
.drawing-tab--draft strong { display: block; font-weight: 500; }
.drawing-tab--draft small { display: none; }
.drawing-pending-dot { position: absolute; top: 5px; right: 5px; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pending-pulse 1.6s ease-in-out infinite; }
@keyframes pending-pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }
.drawing-navigation-all { flex: none; font-size: 12px; color: var(--text-secondary); text-decoration: none; }
.drawing-navigation-all:hover { color: var(--accent-strong); }

/* ---- batch overview strip ---- */
.batch-overview { display: grid; gap: 8px; padding: 0 2px; }
.batch-overview-status { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-secondary); }
.batch-overview-status .status-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--text-muted); }
.batch-overview-status.live { color: var(--accent-strong); }
.batch-overview-status.live .status-dot { background: var(--accent); animation: pending-pulse 1.6s ease-in-out infinite; }
.batch-overview-status.failed { color: var(--error); }
.batch-overview-status.failed .status-dot { background: var(--error); }
.batch-progress { height: 2px; overflow: hidden; background: var(--bg-elevated); border-radius: 2px; }
.batch-progress > span { display: block; height: 100%; background: var(--accent); transition: width 240ms ease; }
.batch-progress--live > span { background: linear-gradient(90deg, transparent, var(--accent), transparent); animation: progress-sweep 2.2s ease-in-out infinite; }
@keyframes progress-sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(320%); } }
.batch-progress--failed > span { background: var(--text-muted); }
.batch-parameters { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 0; min-width: 0; font-size: 12.5px; }
.batch-parameters-prompt { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.batch-parameters-meta { flex: none; color: var(--text-muted); font-size: 11.5px; }
.batch-billing { display: flex; gap: 4px 12px; flex-wrap: wrap; font-size: 11.5px; color: var(--text-muted); }
.batch-billing-refund { color: var(--success); }

/* ---- candidates rail ---- */
.batch-results { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.candidate-batch { min-width: 0; }
.candidate-grid { display: flex; flex-wrap: wrap; gap: 8px; padding: 2px; }
/* Responsive square tiles: widen with the pane, wrap when there are many. */
.candidate-card { position: relative; flex: 1 1 84px; min-width: 84px; max-width: 148px; aspect-ratio: 1 / 1; display: grid; place-items: stretch; padding: 0; overflow: hidden; border-radius: 9px; }
.candidate-card[aria-pressed='true'] { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
.candidate-card :deep(.protected-image), .candidate-placeholder, .candidate-waiting { height: 100%; min-height: 0; border-radius: 8px; }
.candidate-placeholder { display: grid; place-content: center; justify-items: center; gap: 4px; color: var(--text-secondary); font-size: 11px; }
/* The quip needs room to be read: reserve the badge strip and clamp to three lines. */
.candidate-waiting { padding: 8px 4px 20px; }
.candidate-waiting :deep(.waiting-status) { font-size: 10px; gap: 3px; }
.candidate-waiting :deep(.waiting-quip-slot) {
  flex: 0 0 auto; width: 100%; max-width: none; min-height: 0; margin: 3px 0 0; padding: 0 6px;
  font-size: 10.5px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.candidate-waiting :deep(.waiting-mark) { display: none; }
.candidate-badge { position: absolute; left: 0; right: 0; bottom: 0; min-height: 19px; padding: 2px 3px; background: var(--bg-surface); box-shadow: 0 -1px 0 var(--border-subtle); color: var(--text-secondary); font-size: 9.5px; line-height: 1.5; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.candidate-badge--refunded { color: var(--success); }
.candidate-index { position: absolute; top: 3px; left: 4px; font: 600 9.5px var(--font-mono); color: var(--text-inverse); background: rgba(20, 14, 6, .45); border-radius: 3px; padding: 0 3px; }

/* ---- result stage ---- */
.result-stage { min-width: 0; }
.result-frame { position: relative; display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: var(--bg-input); }
.result-frame-top { position: absolute; inset: 10px 12px auto; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 10px; pointer-events: none; }
.result-chip { padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border); background: color-mix(in srgb, var(--bg-surface) 82%, transparent); backdrop-filter: blur(6px); font-size: 11px; color: var(--text-secondary); }
.result-chip-state { padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border-accent); background: color-mix(in srgb, var(--bg-surface) 82%, transparent); font-size: 11px; color: var(--accent-strong); }
.result-chip-state.live { animation: pending-pulse 1.6s ease-in-out infinite; }
.version-preview { height: clamp(320px, 52vh, 560px); min-height: 0; }
.version-preview :deep(.protected-image) { height: 100%; min-height: 0; }
.version-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; height: 100%; background: var(--bg-input); color: var(--text-secondary); font-size: 13px; padding: 24px; text-align: center; }
.result-frame-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; border-top: 1px solid var(--border); background: var(--bg-surface); }
.result-frame-foot :deep(.media-expiry) { font-size: 11px; }
.result-frame-params { color: var(--text-muted); font-size: 11px; }

/* ---- actions ---- */
.version-actions, .version-canvas-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.version-actions { padding-top: 2px; }
.version-actions-spacer { flex: 1; }
.version-canvas-actions label { display: flex; align-items: center; gap: 6px; min-width: 0; }
button, select, textarea { font: inherit; color: var(--text-primary); background: transparent; border: 1px solid var(--border); border-radius: 8px; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; padding: 0 12px; font-size: 12.5px; cursor: pointer; }
button:hover:not(:disabled) { border-color: var(--border-accent); background: var(--bg-hover); }
button:disabled { opacity: .5; cursor: not-allowed; }
.version-primary { background: var(--accent); border-color: var(--accent); color: var(--text-inverse); }
.version-primary:hover:not(:disabled) { background: var(--accent-strong); border-color: var(--accent-strong); }
select { min-width: 0; max-width: 200px; height: 34px; padding: 0 8px; font-size: 12px; }
.version-failure { display: grid; gap: 10px; padding: 12px 14px; background: var(--error-soft); border-radius: 10px; }
.version-failure p { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--error); overflow-wrap: anywhere; }
.version-editor { display: grid; gap: 8px; padding-top: 4px; }
.version-editor > label { display: flex; align-items: center; gap: 6px; font-size: 13px; }
textarea { width: 100%; min-height: 84px; padding: 10px 12px; font-size: 14px; line-height: 1.7; resize: vertical; background: var(--bg-input); }
.version-editor-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 12px; color: var(--text-secondary); }
.version-pending { padding: 12px; background: var(--accent-soft); border-radius: 10px; font-size: 13px; }
.version-pending p { margin: 0 0 10px; }
.version-history-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding-top: 6px; }
.version-history-heading h3 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; font-weight: 500; }
.version-history-heading > span, .version-history-heading h3 span { font-size: 12px; color: var(--text-secondary); }
.version-history { display: flex; gap: 8px; overflow-x: auto; padding: 2px; scrollbar-width: thin; }
.version-history button { display: flex; flex-direction: column; align-items: stretch; gap: 4px; flex: 0 0 96px; width: 96px; padding: 5px; text-align: left; }
.version-history button[aria-pressed='true'] { border-color: var(--accent); background: var(--accent-soft); }
.version-history :deep(.protected-image) { height: 58px; min-height: 0; border-radius: 5px; }
.version-history :deep(.image-placeholder) { min-height: 58px; padding: 4px; font-size: 10px; }
.version-history strong { display: flex; justify-content: space-between; align-items: center; font-size: 11.5px; font-weight: 500; }
.version-history strong span { display: flex; align-items: center; color: var(--text-secondary); gap: 2px; }
.version-history small { color: var(--text-secondary); font-size: 10.5px; }
.version-history-placeholder { display: grid; place-items: center; height: 58px; }
.drawing-next { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
.drawing-next > span { color: var(--text-muted); font-size: 12px; }
.workspace-new-drawing { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 12px; border: 1px solid var(--border); border-radius: 8px; background: transparent; color: var(--text-primary); font: inherit; font-size: 12.5px; cursor: pointer; }
.workspace-new-drawing:hover:not(:disabled) { border-color: var(--border-accent); background: var(--bg-hover); }
button:focus-visible, select:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 900px) {
  .batch-results { flex-direction: column-reverse; }
}
@media (max-width: 560px) {
  .candidate-card { flex-basis: 72px; min-width: 72px; }
  .candidate-waiting :deep(.waiting-quip-slot) { padding: 0 4px; -webkit-line-clamp: 2; }
  .version-preview { height: 46vh; }
  .version-canvas-actions label { width: 100%; }
  .version-canvas-actions select { flex: 1; max-width: none; }
}
@media (pointer: coarse) { button { min-height: 44px; } textarea, select { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) {
  .batch-progress > span, .drawing-pending-dot, .result-chip-state.live, .batch-overview-status.live .status-dot { animation: none; }
}
</style>
