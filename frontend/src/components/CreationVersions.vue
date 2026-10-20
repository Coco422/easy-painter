<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, GitBranch, Layers, Loader2, PencilLine, Sparkles } from 'lucide-vue-next'
import ProtectedImage from './ProtectedImage.vue'
import MediaExpiry from './MediaExpiry.vue'
import { creationVersionRows, type CreationHistory } from '@/lib/creation-versions'
import { mediaAvailable } from '@/lib/media-state'
import { useMediaClock } from '@/composables/useMediaClock'
import type { JobDetailResponse } from '@/lib/types'

const props = defineProps<{
  jobs: JobDetailResponse[]
  parents: CreationHistory['parents']
  selectedId: string
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
}>()
const now = useMediaClock()
const instruction = ref('')
const target = ref('')
const rows = computed(() => creationVersionRows(props.jobs, props.parents))
const selected = computed(() => rows.value.find(row => row.job.job_id === props.selectedId) ?? rows.value[rows.value.length - 1])
const usable = computed(() => !!selected.value && selected.value.job.status === 'succeeded' && mediaAvailable(selected.value.job.media_state ?? 'none', selected.value.job.media_expires_at, now.value))
const statusLabel = { queued: '排队中', processing: '生成中', succeeded: '已完成', failed: '失败' }
const showEditor = ref(false)
watch(() => props.selectedId, () => { showEditor.value = false; instruction.value = '' })
function openEditor() { showEditor.value = true }
</script>

<template>
  <section v-if="selected" class="version-workspace" aria-label="作品版本">
    <div class="version-title"><strong>V{{ selected.number }} <span>{{ selected.parentNumber ? `基于 V${selected.parentNumber} 修改` : selected.parentId ? '来自较早版本' : '独立创作' }}</span></strong><span>{{ statusLabel[selected.job.status] }}</span></div>
    <div class="version-preview">
      <ProtectedImage v-if="selected.job.status === 'succeeded'" :key="selected.job.job_id" :src="selected.job.image_url" :state="selected.job.media_state" :expires-at="selected.job.media_expires_at" :alt="`创作版本 V${selected.number}`" eager preview @invalid="emit('refresh', selected.job)" />
      <div v-else class="version-placeholder" role="status"><Loader2 v-if="selected.job.status !== 'failed'" :size="28" class="version-spinner" /><strong>{{ statusLabel[selected.job.status] }}</strong><span>{{ selected.job.error_message || '结果会自动显示在这里，无需重复提交。' }}</span></div>
    </div>
    <div class="version-meta"><span>{{ selected.job.model_label || selected.job.model }} · {{ selected.job.size }}</span><MediaExpiry v-if="selected.job.status === 'succeeded'" :state="selected.job.media_state ?? 'none'" :expires-at="selected.job.media_expires_at" /></div>
    <div class="version-actions">
      <button type="button" class="version-primary" :disabled="!usable || busy || pending" @click="openEditor"><PencilLine :size="15" />继续修改 V{{ selected.number }}</button>
      <button type="button" :disabled="!usable || busy" @click="emit('details', selected.job)">详情与下载</button>
      <button type="button" :disabled="!usable || busy" @click="emit('gallery', selected.job)">加入画廊</button>
    </div>
    <div class="version-canvas-actions">
      <label>目标画布<select v-model="target" :disabled="busy"><option value="">新建画布</option><option v-for="canvas in canvases" :key="canvas.id" :value="canvas.id">{{ canvas.title }}</option></select></label>
      <button type="button" :disabled="!usable || busy" @click="emit('canvas', selected.job, target)"><Layers :size="15" />{{ busy ? '处理中…' : '加入画布并打开' }}</button>
    </div>
    <div v-if="showEditor && usable && !pending" class="version-editor">
      <label :for="`revision-${selected.job.job_id}`"><GitBranch :size="15" />基于 V{{ selected.number }} 生成新版本，保留已有版本</label>
      <textarea :id="`revision-${selected.job.job_id}`" v-model="instruction" rows="3" :maxlength="maxLength" :disabled="busy" placeholder="例如：改成蓝色配色，保留现有布局和文字" />
      <div class="version-editor-footer"><span>{{ editModel || '暂无支持改图的模型' }} · {{ editSize }} · {{ editCost }} 丝 / 次</span><button type="button" class="version-primary" :disabled="busy || !instruction.trim() || !editModel" @click="emit('revise', instruction)"><Sparkles :size="15" />{{ busy ? '正在提交…' : '生成修改版' }}</button></div>
    </div>
    <div v-if="pending" class="version-pending" role="status"><p>上次改图的提交结果尚未确认。确认会复用原请求，不会创建第二个任务。</p><button type="button" :disabled="busy" @click="emit('confirm')">确认上次改图任务</button></div>
    <div class="version-history-heading"><h3><GitBranch :size="16" />版本记录 <span>{{ rows.length }}</span></h3><span>可选中旧版本分叉修改</span></div>
    <div class="version-history" role="group" aria-label="选择创作版本">
      <button v-for="row in rows" :key="row.job.job_id" type="button" :aria-pressed="selected.job.job_id === row.job.job_id" :aria-label="`V${row.number}${row.parentNumber ? `，基于 V${row.parentNumber}` : '，独立创作'}，${statusLabel[row.job.status]}`" @click="emit('select', row.job.job_id)">
        <ProtectedImage v-if="row.job.status === 'succeeded'" :src="row.job.thumbnail_url || row.job.image_url" :state="row.job.media_state" :expires-at="row.job.media_expires_at" :alt="`V${row.number} 缩略图`" />
        <span v-else class="version-history-placeholder">{{ statusLabel[row.job.status] }}</span>
        <strong>V{{ row.number }} <span v-if="row.parentNumber"><ArrowRight :size="11" /> V{{ row.parentNumber }}</span></strong><small>{{ row.parentNumber ? `基于 V${row.parentNumber} 修改` : row.parentId ? '来自较早版本' : '独立创作' }}</small>
      </button>
    </div>
    <p class="version-local-note">最近 100 个版本的关系保存在当前浏览器，按账号隔离；图片保留期不因此延长。</p>
  </section>
</template>

<style scoped>
.version-workspace { display: grid; gap: 16px; margin-top: 20px; min-width: 0; }
.version-title, .version-meta, .version-editor-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; }
.version-title { font-size: 13px; }
.version-title strong { font-weight: 500; }
.version-title strong span { color: var(--text-secondary); margin-left: 8px; }
.version-title > span, .version-meta, .version-editor-footer > span { color: var(--text-secondary); font-size: 12px; }
.version-preview { height: 340px; overflow: hidden; border: 1px solid var(--border); border-radius: 6px; }
.version-preview :deep(.protected-image) { background: var(--bg-input); }
.version-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; height: 100%; background: var(--bg-input); color: var(--text-secondary); font-size: 13px; padding: 24px; text-align: center; }
.version-spinner { animation: version-spin 1.4s linear infinite; }
@keyframes version-spin { to { transform: rotate(360deg); } }
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
@media (max-width: 450px) { .version-preview { height: 240px; } .version-canvas-actions label { width: 100%; } .version-canvas-actions select { flex: 1; max-width: none; } }
@media (pointer: coarse) { button { min-height: 44px; } textarea, select { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .version-spinner { animation: none; } }
</style>
