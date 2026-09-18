<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Check, Share2 } from 'lucide-vue-next'
import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { authState, getAuthHeader } from '@/lib/auth'
import { deleteJob } from '@/lib/api'
import { setGallery, setFavorite, submitCommunity, withdrawCommunity, type Artwork } from '@/lib/artworks'
import { mediaAvailable } from '@/lib/media-state'
import { useMediaClock } from '@/composables/useMediaClock'
import { imageDownloadFilename } from '@/lib/image-download'
import { artworkShare } from '@/lib/artwork-share'

const props = defineProps<{ item: Artwork; initialAction?: 'gallery' }>()
const emit = defineEmits<{ close: []; updated: [item: Artwork]; deleted: [item: Artwork]; invalid: [] }>()
const router = useRouter()
const now = useMediaClock()
const available = computed(() => mediaAvailable(props.item.media_state, props.item.media_expires_at, now.value))
const shareTarget = computed(() => artworkShare(props.item, window.location.origin, now.value))
const busy = ref(false)
const error = ref('')
const notice = ref('')
const shareCopied = ref(false)
const sharing = ref(false)
let shareResetTimer: number | undefined
const action = ref<'gallery' | 'community' | null>(null)
const promptPublic = ref(true)
const tags = ref('')
const consent = ref(false)
const panel = ref<HTMLElement | null>(null)
const previousFocus = document.activeElement as HTMLElement | null
let downloadController: AbortController | undefined
const submissionLabels: Record<string,string> = { none: '未投稿', pending: '待审核', approved: '已收录', rejected: '已拒绝', withdrawn: '已撤回', expired: '投稿已过期' }

function close() { if (!busy.value) emit('close') }
function requireLogin() {
  if (authState.token) return true
  void router.push('/login'); emit('close'); return false
}
async function perform(operation: () => Promise<Artwork>) {
  if (!requireLogin()) return
  busy.value = true; error.value = ''; notice.value = ''
  try { emit('updated', await operation()); action.value = null }
  catch (e) { error.value = e instanceof Error ? e.message : '操作失败，请重试。' }
  finally { busy.value = false }
}
function gallery() {
  if (props.item.is_in_gallery) { void perform(() => setGallery(props.item, false)); return }
  action.value = 'gallery'; tags.value = props.item.tags.join('，'); promptPublic.value = props.item.is_prompt_public
}
function publish() {
  if (!requireLogin()) return
  action.value = 'community'; consent.value = false; error.value = ''
}
async function download() {
  if (!available.value || !props.item.image_url || busy.value) return
  busy.value = true; error.value = ''
  downloadController = new AbortController()
  try {
    const response = await fetch(props.item.image_url, { headers: getAuthHeader(), signal: downloadController.signal })
    if (!response.ok) { if ([401,403,404,410].includes(response.status)) emit('invalid'); throw new Error('图片已失效或暂时无法下载。') }
    const blob = await response.blob()
    if (!available.value) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = imageDownloadFilename(props.item.id, blob.type)
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { if (!downloadController.signal.aborted) error.value = e instanceof Error ? e.message : '下载失败。' }
  finally { busy.value = false }
}
async function share() {
  const target = shareTarget.value
  if (!target || busy.value || sharing.value) return
  sharing.value = true; error.value = ''; notice.value = ''
  try {
    if (navigator.share) {
      await navigator.share(target.data)
      return
    }
    await navigator.clipboard.writeText(target.data.url)
    shareCopied.value = true
    notice.value = target.copyNotice
    window.clearTimeout(shareResetTimer)
    shareResetTimer = window.setTimeout(() => { shareCopied.value = false }, 1600)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    error.value = '暂时无法分享，请稍后重试。'
  } finally { sharing.value = false }
}
async function remove() {
  if (!confirm('删除这条生成记录和原始图片？已经收录的社区版本将继续保留。')) return
  busy.value = true
  try { await deleteJob(props.item.id); emit('deleted', props.item); emit('close') }
  catch (e) { error.value = e instanceof Error ? e.message : '删除失败。' }
  finally { busy.value = false }
}
async function copy() {
  try { await navigator.clipboard.writeText(props.item.prompt); notice.value = '提示词已复制' }
  catch { error.value = '复制失败，请手动选择提示词。' }
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
  if (event.key === 'Tab' && panel.value) {
    const focusable = [...panel.value.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), textarea')]
    const first = focusable[0], last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
watch(available, value => { if (!value) { action.value = null; downloadController?.abort() } })
onMounted(async () => { if (props.initialAction === 'gallery' && !props.item.is_in_gallery) gallery(); document.addEventListener('keydown', keydown); await nextTick(); panel.value?.querySelector('button')?.focus() })
onBeforeUnmount(() => { document.removeEventListener('keydown', keydown); downloadController?.abort(); window.clearTimeout(shareResetTimer); previousFocus?.focus() })
</script>
<template>
  <div class="modal-backdrop" @click.self="close">
    <section ref="panel" class="modal-panel artwork-dialog" role="dialog" aria-modal="true" aria-labelledby="artwork-dialog-title">
      <header class="dialog-header"><h2 id="artwork-dialog-title">{{ available ? '作品详情' : '生成记录' }}</h2><button class="ghost-button" :disabled="busy" @click="close">关闭</button></header>
      <div class="dialog-image"><ProtectedImage :src="item.image_url" :state="item.media_state" :expires-at="item.media_expires_at" :alt="item.title || '生成作品'" eager @invalid="emit('invalid')" /></div>
      <div class="dialog-body">
        <MediaExpiry :state="item.media_state" :expires-at="item.media_expires_at" :permanent="item.retention_kind === 'permanent'" />
        <p v-if="item.retention_kind === 'permanent'" class="dialog-note">当前查看社区收录副本，原始生成文件按原期限清理。</p>
        <p v-if="error" class="feedback-banner" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
        <div class="dialog-actions">
          <button class="ghost-button" :disabled="busy || !available" @click="download">下载原图</button>
          <button class="ghost-button share-action" :disabled="busy || sharing || !shareTarget" @click="share">
            <Check v-if="shareCopied" :size="16" aria-hidden="true" />
            <Share2 v-else :size="16" aria-hidden="true" />
            {{ shareCopied ? '已复制' : '分享' }}
          </button>
          <button class="ghost-button" :disabled="busy || (!available && !item.is_favorite)" @click="perform(() => setFavorite(item, !item.is_favorite))">{{ item.is_favorite ? '取消收藏' : '收藏' }}</button>
          <button v-if="item.is_owner" class="ghost-button" :disabled="busy || (!available && !item.is_in_gallery)" @click="gallery">{{ item.is_in_gallery ? '移出画廊' : '加入画廊' }}</button>
          <button v-if="item.is_owner && item.submission_status === 'pending'" class="ghost-button" :disabled="busy" @click="perform(() => withdrawCommunity(item))">撤回投稿</button>
          <button v-else-if="item.is_owner && item.submission_status !== 'approved'" class="ghost-button" :disabled="busy || !available" @click="publish">投稿社区</button>
        </div>
        <p v-if="available && !shareTarget && item.is_owner" class="dialog-note">分享前请先加入画廊，并在个人中心开启公开总开关。</p>
        <form v-if="action === 'gallery'" class="action-panel" @submit.prevent="perform(() => setGallery(item, true, tags.split(/[,，]/).map(t => t.trim()).filter(Boolean).slice(0, 5), promptPublic))">
          <h3>加入个人画廊</h3><p>画廊用于展示作品，不会延长保存时间。</p>
          <p v-if="!authState.user?.is_public">当前画廊尚未公开。加入后仅你可见，可前往<router-link to="/profile" @click="emit('close')">个人中心</router-link>开启公开总开关。</p>
          <label>标签（最多 5 个，逗号分隔）<input v-model="tags" maxlength="104" /></label>
          <label class="check-label"><input v-model="promptPublic" type="checkbox" />在个人画廊公开提示词</label>
          <div class="dialog-actions"><button class="primary-button" :disabled="busy">确认加入</button><button type="button" class="ghost-button" @click="action = null">取消</button></div>
        </form>
        <form v-if="action === 'community'" class="action-panel" @submit.prevent="perform(() => submitCommunity(item))">
          <h3>投稿社区，等待审核</h3>
          <p v-if="!authState.user?.is_public">请先到<router-link to="/profile" @click="emit('close')">个人中心</router-link>开启公开作品总开关。</p>
          <p>待审核不延长图片有效期；请在到期前完成审核。通过后社区会独立长期保存图片和提示词，原作删除或关闭画廊不会撤下社区版本，社区下架由管理员处理。</p>
          <label class="check-label"><input v-model="consent" type="checkbox" />我同意审核通过后公开图片和提示词，并独立长期保存</label>
          <div class="dialog-actions"><button class="primary-button" :disabled="busy || !consent || !authState.user?.is_public">提交审核</button><button type="button" class="ghost-button" @click="action = null">取消</button></div>
        </form>
        <p v-if="item.is_owner" class="dialog-note">社区投稿：{{ item.submission_status === 'pending' && !available ? '投稿已过期' : submissionLabels[item.submission_status] }}<span v-if="item.review_reason"> · {{ item.review_reason }}</span></p>
        <template v-if="item.prompt"><h3>提示词</h3><p class="dialog-prompt">{{ item.prompt }}</p><div class="dialog-actions"><button class="ghost-button" @click="copy">复制提示词</button><button class="ghost-button" @click="router.push({ path: '/create', query: { prompt: item.prompt } }); emit('close')">再次创作</button></div></template>
        <p v-else class="dialog-note">{{ available ? '作者未公开提示词' : '作品不可访问' }}</p>
        <p v-if="item.error_message" class="feedback-banner">{{ item.error_message }}</p>
        <div class="dialog-meta"><span v-if="item.model">{{ item.model }} · {{ item.size }}</span><span v-if="item.created_at">{{ new Date(item.created_at).toLocaleString('zh-CN') }}</span><span v-if="item.credit_cost != null">{{ item.credit_cost }} 丝 · {{ ({ not_charged: '未扣费', reserved: '已预扣', settled: '已结算', refunded: '已全额退款' } as Record<string, string>)[item.billing_status ?? 'not_charged'] }}</span><router-link v-if="item.username" :to="`/gallery/${encodeURIComponent(item.username)}`" @click="emit('close')">{{ item.username }} 的画廊</router-link></div>
        <button v-if="item.is_owner" class="delete-record" :disabled="busy" @click="remove">删除生成记录</button>
      </div>
    </section>
  </div>
</template>
<style scoped>
.artwork-dialog { width: min(900px, 96vw); max-height: 92vh; overflow-y: auto; }
.dialog-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; }
.dialog-header h2 { font-size: 20px; margin: 0; }
.dialog-image { max-height: 52vh; overflow: hidden; }
.dialog-image :deep(img) { max-height: 52vh; }
.dialog-body { padding: 24px; }
.dialog-actions, .dialog-meta { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 16px 0; }
.share-action { display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.dialog-note, .dialog-meta { font-size: 13px; color: var(--text-secondary); line-height: 1.7; }
.dialog-prompt { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.action-panel { padding: 20px; border: 1px solid var(--border-accent); border-radius: var(--radius-md); margin: 16px 0; background: var(--bg-elevated); }
.action-panel p { font-size: 14px; line-height: 1.8; }
.action-panel label { display: block; line-height: 1.8; }
.action-panel input:not([type='checkbox']) { display: block; width: 100%; margin: 8px 0; padding: 8px; background: var(--bg-input); color: var(--text-primary); border: 1px solid var(--border); border-radius: var(--radius-sm); }
.check-label { margin: 12px 0; }
.delete-record { border: 0; background: none; color: var(--error); cursor: pointer; margin-top: 20px; padding: 4px 0; }
</style>
