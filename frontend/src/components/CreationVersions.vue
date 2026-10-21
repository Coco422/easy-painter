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
watch([() => props.selectedId, () => props.drafting], () => { showEditor.value = false; instruction.value = '' })
function openEditor() { showEditor.value = true }
function billingLabel(job: JobDetailResponse) {
  const labels: Record<string, string> = { reserved: '已预扣', settled: '已结算', refunded: '已全额退回', not_charged: '未扣费' }
  const label = labels[job.billing_status] ?? '计费待确认'
  return job.billing_status === 'not_charged' ? label : `${label} ${job.credit_cost} 丝`
}
</script>

<template>
  <section v-if="selected" class="version-workspace" aria-label="绘图结果">
    <nav class="drawing-navigation" aria-label="最近绘图">
      <span class="drawing-navigation-label">最近绘图</span>
      <div class="drawing-tabs" role="group" aria-label="切换绘图批次">
        <button v-if="drafting" type="button" class="drawing-tab drawing-tab--draft" aria-pressed="true"><Plus :size="14" aria-hidden="true" /><strong>新的绘图</strong><small>待创作</small></button>
        <button v-for="batch in batches" :key="batch.id" type="button" class="drawing-tab" :aria-pressed="!drafting && currentBatch?.id === batch.id" :aria-label="`查看第 ${batch.number} ${batch.candidates.length > 1 ? '批绘图' : '次绘图'}，${batch.candidates.length} 张${batch.candidates.length > 1 ? '候选图' : '图片'}${batch.pending ? `，${batch.pending} 张生成中` : ''}`" :title="batch.candidates[0]?.job.prompt" @click="emit('select', batch.candidates[0]!.job.job_id)">
          <strong>绘图 {{ batch.number }} <span>{{ batch.candidates[0]?.job.prompt || '未命名绘图' }}</span></strong><small><span v-if="batch.pending" class="drawing-pending-dot" aria-hidden="true" />{{ batch.pending ? `${batch.pending} 张生成中` : `${batch.candidates.length} 张${batch.candidates.length > 1 ? '候选图' : '图片'}` }}</small>
        </button>
      </div>
    </nav>
    <template v-if="!drafting && currentBatch">
    <section class="batch-overview" :aria-label="`${batchTitle}进度与计费`">
      <div class="batch-overview-heading"><h3>{{ batchTitle }} <span>{{ hasPeers ? `${currentBatch.candidates.length} 张候选图` : '单张作品' }}<span v-if="summary.total > currentBatch.candidates.length"> · {{ summary.total - currentBatch.candidates.length }} 次修改</span></span></h3><span role="status">{{ currentBatch.pending ? `${currentBatch.pending} 张生成中` : '生成已结束' }}</span></div>
      <div class="batch-progress" :class="{ 'batch-progress--failed': summary.failed }" role="progressbar" :aria-label="`${batchTitle}任务完成进度`" aria-valuemin="0" :aria-valuemax="summary.total" :aria-valuenow="summary.finished" :aria-valuetext="`${summary.finished} / ${summary.total} 个任务已结束，${summary.succeeded} 张成功，${summary.failed} 张失败`"><span :style="{ width: `${summary.finished / summary.total * 100}%` }" /></div>
      <div class="batch-overview-meta"><span>已生成 {{ summary.succeeded }} / {{ summary.total }} 张<span v-if="summary.failed" class="batch-failure-count"> · {{ summary.failed }} 张失败</span></span><span class="batch-billing"><span v-if="summary.reserved">已预扣 {{ summary.reserved }} 丝</span><span v-if="summary.settled">已结算 {{ summary.settled }} 丝</span><span v-if="summary.refunded">已退回 {{ summary.refunded }} 丝</span><span v-if="!summary.reserved && !summary.settled && !summary.refunded">本批未扣费</span></span></div>
      <details class="batch-prompt"><summary>{{ currentBatch.candidates[0]?.job.prompt }}</summary><p>{{ currentBatch.candidates[0]?.job.prompt }}</p></details>
      <p class="batch-parameters">{{ currentBatch.candidates[0]?.job.model_label || currentBatch.candidates[0]?.job.model }} · {{ currentBatch.candidates[0]?.job.size }} <span v-if="hasPeers">候选图独立生成，选中一张继续修改</span></p>
    </section>
    <section v-if="hasPeers" class="candidate-batch" :aria-label="`第 ${currentBatch.number} 批候选图`">
      <div class="candidate-grid" role="group" :aria-label="`选择第 ${currentBatch.number} 批候选图`">
        <button v-for="candidate in currentBatch.candidates" :key="candidate.id" type="button" class="candidate-card" :aria-pressed="selected.rootId === candidate.id" :aria-label="`第 ${currentBatch.number} 批，${candidate.label}，${statusLabel[candidate.job.status]}`" @click="emit('select', candidate.job.job_id)">
          <ProtectedImage v-if="candidate.job.status === 'succeeded'" :src="candidate.job.thumbnail_url || candidate.job.image_url" :state="candidate.job.media_state" :expires-at="candidate.job.media_expires_at" :alt="candidate.label" @invalid="emit('refresh', candidate.job)" />
          <GenerationWaiting v-else-if="candidate.job.status === 'queued' || candidate.job.status === 'processing'" class="candidate-waiting" :status="candidate.job.status" :quip="quips.get(candidate.job.job_id)!" compact />
          <span v-else class="candidate-placeholder" role="status">{{ statusLabel[candidate.job.status] }}</span>
          <span class="candidate-caption"><strong>{{ candidate.label }}</strong><small>{{ candidate.rows.some(row => row.parentId) ? `${candidate.rows.filter(row => row.parentId).length} 个修改版本` : statusLabel[candidate.job.status] }}</small></span>
          <span class="candidate-billing" :class="{ 'candidate-billing--refunded': candidate.job.billing_status === 'refunded' }">{{ billingLabel(candidate.job) }}</span>
        </button>
      </div>
    </section>
    <div v-if="hasPeers || hasBranch" class="version-title"><strong>{{ batchTitle }} · {{ resultLabel }} <span v-if="sourceLabel">{{ sourceLabel }}</span></strong><span>{{ statusLabel[selected.job.status] }}</span></div>
    <div class="version-preview">
      <ProtectedImage v-if="selected.job.status === 'succeeded'" :key="selected.job.job_id" :src="selected.job.image_url" :state="selected.job.media_state" :expires-at="selected.job.media_expires_at" :alt="hasPeers || hasBranch ? `${batchTitle} · ${resultLabel}` : '生成结果'" eager preview @invalid="emit('refresh', selected.job)" />
      <GenerationWaiting v-else-if="selected.job.status === 'queued' || selected.job.status === 'processing'" :key="selected.job.job_id" :status="selected.job.status" :quip="quips.get(selected.job.job_id)!" :hint="selected.job.error_message" />
      <div v-else class="version-placeholder" role="status"><strong>{{ statusLabel[selected.job.status] }}</strong><span>{{ selected.job.error_message || '这张图片生成失败。' }}</span></div>
    </div>
    <div v-if="hasPeers || hasBranch || selected.job.status === 'succeeded'" class="version-meta"><span v-if="hasPeers || hasBranch">{{ selected.job.model_label || selected.job.model }} · {{ selected.job.size }} · {{ billingLabel(selected.job) }}</span><MediaExpiry v-if="selected.job.status === 'succeeded'" :state="selected.job.media_state ?? 'none'" :expires-at="selected.job.media_expires_at" /></div>
    <div v-if="selected.job.status === 'failed'" class="version-failure" role="alert"><p>{{ selected.job.error_message || '这张图片生成失败。' }}<span v-if="selected.job.billing_status === 'refunded'"> {{ selected.job.credit_cost }} 丝已全额退回余额。</span></p><div class="version-actions"><button type="button" :disabled="busy || pending" @click="emit('retry', selected.job)">重新生成</button><button type="button" :disabled="busy" @click="emit('dismiss', selected.job.job_id)">收起这张图</button></div></div>
    <div v-else class="version-actions">
      <button type="button" class="version-primary" :disabled="!usable || busy || pending" @click="openEditor"><PencilLine :size="15" />继续修改{{ selected.parentId ? ` V${selected.number}` : '这张图' }}</button>
      <button type="button" :disabled="!usable || busy" @click="emit('details', selected.job)">详情与下载</button>
      <button type="button" :disabled="!usable || busy" @click="emit('gallery', selected.job)">加入画廊</button>
    </div>
    <div v-if="selected.job.status === 'succeeded'" class="version-canvas-actions">
      <label>目标画布<select v-model="target" :disabled="busy"><option value="">新建画布</option><option v-for="canvas in canvases" :key="canvas.id" :value="canvas.id">{{ canvas.title }}</option></select></label>
      <button type="button" :disabled="!usable || busy" @click="emit('canvas', selected.job, target)"><Layers :size="15" />{{ busy ? '处理中…' : '加入画布并打开' }}</button>
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
    <div class="drawing-next"><span>想画点不一样的？之前的作品会保留。</span><button type="button" :disabled="busy || canStartNew === false" @click="emit('new')"><Plus :size="15" aria-hidden="true" />新绘图</button></div>
    </template>
  </section>
</template>

<style scoped>
.version-workspace { display: grid; gap: 16px; margin-top: 20px; min-width: 0; }
.drawing-navigation { display: grid; gap: 10px; min-width: 0; }
.drawing-navigation-label { font-size: 11px; color: var(--text-secondary); }
.drawing-tabs { display: flex; align-items: stretch; gap: 8px; overflow-x: auto; padding: 3px 3px 8px; margin: -3px; scrollbar-width: thin; }
.drawing-tab { display: grid; justify-content: start; gap: 6px; flex: 0 0 170px; min-width: 0; padding: 10px 12px; text-align: left; }
.drawing-tab strong { display: flex; align-items: baseline; gap: 8px; min-width: 0; font-size: 12px; font-weight: 500; }
.drawing-tab strong span { display: block; max-width: 88px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-size: 11px; }
.drawing-tab small { display: flex; align-items: center; gap: 5px; color: var(--text-secondary); font-size: 11px; }
.drawing-tab[aria-pressed='true'] { border-color: var(--accent); background: var(--accent-soft); }
.drawing-tab--draft { grid-template-columns: auto 1fr; align-content: center; flex-basis: 130px; }
.drawing-tab--draft small { grid-column: 2; }
.drawing-pending-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.batch-overview { display: grid; gap: 12px; padding: 16px 0 4px; border-top: 1px solid var(--border); }
.batch-overview-heading, .batch-overview-meta { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; }
.batch-overview-heading h3 { margin: 0; font-size: 14px; font-weight: 500; }
.batch-overview-heading h3 > span { margin-left: 8px; }
.batch-overview-heading span, .batch-overview-meta, .batch-parameters, .batch-prompt { font-size: 12px; color: var(--text-secondary); }
.batch-progress { height: 4px; overflow: hidden; background: var(--bg-elevated); border-radius: 2px; }
.batch-progress > span { display: block; height: 100%; background: var(--accent); transition: width 200ms ease; }
.batch-progress--failed > span { background: var(--text-muted); }
.batch-failure-count { color: var(--error); }
.batch-billing { display: flex; gap: 6px 12px; flex-wrap: wrap; }
.batch-prompt { min-width: 0; }
.batch-prompt summary { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.batch-prompt summary::before { content: '描述 · '; color: var(--text-muted); }
.batch-prompt p { margin: 10px 0 0; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.batch-parameters { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin: 0; }
.batch-parameters > span { color: var(--text-muted); font-size: 11px; }
.candidate-billing { color: var(--text-secondary); font-size: 11px; }
.candidate-billing--refunded { color: var(--success); }
.version-failure { display: grid; gap: 12px; padding: 14px; background: var(--error-soft); border-radius: 6px; }
.version-failure p { margin: 0; font-size: 12px; line-height: 1.8; color: var(--error); overflow-wrap: anywhere; }
.drawing-next { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding-top: 20px; border-top: 1px solid var(--border); }
.drawing-next > span { color: var(--text-secondary); font-size: 12px; }
.candidate-batch { display: grid; gap: 12px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
.candidate-caption { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; }
.candidate-caption small { color: var(--text-secondary); font-size: 12px; }
.candidate-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.candidate-grid:has(> :only-child) { grid-template-columns: minmax(0, 1fr); }
.candidate-card { display: flex; flex-direction: column; align-items: stretch; gap: 10px; min-width: 0; padding: 10px; text-align: left; }
.candidate-card[aria-pressed='true'] { border-color: var(--accent); background: var(--accent-soft); }
.candidate-card :deep(.protected-image), .candidate-placeholder, .candidate-waiting { height: 200px; min-height: 0; border-radius: 3px; }
.candidate-placeholder { display: grid; place-content: center; justify-items: center; gap: 12px; color: var(--text-secondary); }
.candidate-caption strong { font-weight: 500; }
.version-title, .version-meta, .version-editor-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; }
.version-title { font-size: 13px; }
.version-title strong { font-weight: 500; }
.version-title strong span { color: var(--text-secondary); margin-left: 8px; }
.version-title > span, .version-meta, .version-editor-footer > span { color: var(--text-secondary); font-size: 12px; }
.version-preview { height: 340px; overflow: hidden; border: 1px solid var(--border); border-radius: 6px; }
.version-preview :deep(.protected-image) { background: var(--bg-input); }
.version-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; height: 100%; background: var(--bg-input); color: var(--text-secondary); font-size: 13px; padding: 24px; text-align: center; }
.version-actions, .version-canvas-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
button, select, textarea { font: inherit; color: var(--text-primary); background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 11px; font-size: 12px; cursor: pointer; }
button:hover:not(:disabled) { border-color: var(--border-accent); background: var(--bg-elevated); }
button:disabled { opacity: .5; cursor: not-allowed; }
.version-primary { background: var(--accent); border-color: var(--accent); color: var(--text-inverse); }
.version-primary:hover:not(:disabled) { background: var(--accent-strong); }
.version-canvas-actions label { display: flex; gap: 8px; align-items: center; color: var(--text-secondary); font-size: 12px; min-width: 0; }
select { min-width: 0; max-width: 220px; padding: 8px; font-size: 12px; }
.version-editor { display: grid; gap: 10px; border-top: 1px solid var(--border); padding-top: 16px; }
.version-editor > label { display: flex; align-items: center; gap: 6px; font-size: 13px; }
textarea { width: 100%; min-height: 88px; padding: 12px; font-size: 14px; line-height: 1.7; resize: vertical; }
.version-pending { padding: 12px; background: var(--accent-soft); border-radius: 6px; font-size: 13px; }
.version-pending p { margin: 0 0 12px; }
.version-history-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; border-top: 1px solid var(--border); padding-top: 20px; }
.version-history-heading h3 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; font-weight: 500; }
.version-history-heading > span, .version-history-heading h3 span { font-size: 12px; color: var(--text-secondary); }
.version-history { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 10px; }
.version-history button { display: flex; flex-direction: column; align-items: stretch; gap: 6px; padding: 8px; text-align: left; }
.version-history button[aria-pressed='true'] { border-color: var(--accent); background: var(--accent-soft); }
.version-history :deep(.protected-image) { height: 70px; min-height: 0; border-radius: 3px; }
.version-history :deep(.image-placeholder) { min-height: 70px; padding: 4px; font-size: 11px; }
.version-history strong { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 500; }
.version-history strong span { display: flex; align-items: center; color: var(--text-secondary); gap: 2px; }
.version-history small, .version-local-note { color: var(--text-secondary); font-size: 11px; }
.version-history-placeholder { display: grid; place-items: center; height: 70px; }
.version-local-note { margin: 0; line-height: 1.7; }
button:focus-visible, select:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
@media (max-width: 450px) { .candidate-card :deep(.protected-image), .candidate-placeholder, .candidate-waiting { height: 120px; } .version-preview { height: 240px; } .version-canvas-actions label { width: 100%; } .version-canvas-actions select { flex: 1; max-width: none; } }
@media (pointer: coarse) { button { min-height: 44px; } textarea, select { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .batch-progress > span { transition: none; } }
</style>
