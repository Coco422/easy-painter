<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NInput, NModal, NPagination, NSelect, NSpace, useMessage } from 'naive-ui'
import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { fetchSubmissions, reviewSubmission, type Submission } from '@/lib/artworks'
import { ApiError } from '@/lib/api'
import { useMediaClock, syncMediaClock } from '@/composables/useMediaClock'
import { mediaAvailable } from '@/lib/media-state'
const emit = defineEmits<{ changed: []; 'auth-expired': [] }>()
const message = useMessage(), now = useMediaClock()
const state = ref('pending'), page = ref(1), total = ref(0)
const items = ref<Submission[]>([]), selected = ref<Submission | null>(null)
const loading = ref(false), saving = ref(false), reason = ref('')
const options = [ ['pending','待审核'], ['approved','已收录'], ['rejected','已拒绝'], ['withdrawn','已撤回'], ['expired','已过期'], ['all','全部'] ].map(([value,label]) => ({value,label}))
const reviewable = computed(() => !!selected.value && selected.value.submission_status === 'pending' && mediaAvailable(selected.value.media_state, selected.value.media_expires_at, now.value))
let generation = 0
function handleError(e: unknown) {
  if (e instanceof ApiError && e.status === 401) emit('auth-expired')
  message.error(e instanceof Error ? e.message : '审核操作失败。')
}
async function load() {
  const ticket = ++generation; loading.value = true
  try {
    const data = await fetchSubmissions(state.value, page.value)
    if (ticket !== generation) return
    items.value = data.items; total.value = data.total; syncMediaClock(data.server_time)
  } catch (e) { if (ticket === generation) handleError(e) }
  finally { if (ticket === generation) loading.value = false }
}
function open(item: Submission) { selected.value = item; reason.value = '' }
async function review(decision: 'approve' | 'reject') {
  if (!selected.value || !reviewable.value || saving.value) return
  if (decision === 'reject' && !reason.value.trim()) { message.warning('请填写拒绝原因，让作者知道如何调整。'); return }
  saving.value = true
  try {
    await reviewSubmission(selected.value.id, decision, reason.value.trim())
    selected.value = null; await load(); emit('changed')
    message.success(decision === 'approve' ? '已通过审核并保存独立社区副本。' : '已拒绝，原因已反馈给作者。')
  } catch (e) { handleError(e); await load() }
  finally { saving.value = false }
}
watch(state, () => { page.value = 1; void load() })
watch(page, load)
void load()
</script>
<template>
  <div class="review-queue">
    <NSpace align="center"><NSelect v-model:value="state" :options="options" style="width: 150px" /><NButton :loading="loading" @click="load">刷新审核队列</NButton><span>仅显示用户主动投稿。待审不延长图片有效期。</span></NSpace>
    <p v-if="!loading && !items.length" class="empty">暂无投稿</p>
    <div v-for="item in items" :key="item.id" class="submission-row">
      <button class="preview" :aria-label="`查看 ${item.username} 的投稿`" @click="open(item)"><ProtectedImage :src="item.thumbnail_url" :state="item.media_state" :expires-at="item.media_expires_at" admin /></button>
      <div class="submission-info"><strong>{{ item.username || '原作者' }}</strong><p>{{ item.prompt || '作品已失效' }}</p><MediaExpiry :state="item.media_state" :expires-at="item.media_expires_at" :permanent="item.retention_kind === 'permanent'" /><small>提交于 {{ new Date(item.submitted_at).toLocaleString('zh-CN') }} · {{ options.find(o => o.value === item.submission_status)?.label }}</small><p v-if="item.review_reason">{{ item.review_reason }}</p></div>
      <NButton @click="open(item)">{{ item.submission_status === 'pending' ? '审核' : '查看' }}</NButton>
    </div>
    <NPagination v-if="total" v-model:page="page" :page-size="25" :item-count="total" />
    <NModal :show="!!selected" preset="card" title="审核社区投稿" style="width: min(800px, 94vw)" :mask-closable="!saving" :closable="!saving" @update:show="value => { if (!value) selected = null }">
      <template v-if="selected">
        <div class="review-original"><ProtectedImage :src="selected.image_url" :state="selected.media_state" :expires-at="selected.media_expires_at" eager admin /></div>
        <MediaExpiry :state="selected.media_state" :expires-at="selected.media_expires_at" :permanent="selected.retention_kind === 'permanent'" />
        <p class="review-prompt">{{ selected.prompt }}</p><p v-if="selected.review_reason">处理意见：{{ selected.review_reason }}</p>
        <template v-if="selected.submission_status === 'pending'">
          <p v-if="!reviewable">图片已到期，无法继续审核。请关闭并刷新队列。</p>
          <p v-else>用户已确认公开图片和提示词。通过后独立长期保存；请检查两者是否适合展示。</p>
          <NInput v-model:value="reason" type="textarea" placeholder="拒绝时必填处理原因" maxlength="1000" />
          <NSpace class="review-actions"><NButton type="primary" :disabled="!reviewable" :loading="saving" @click="review('approve')">通过并收录</NButton><NButton type="error" :disabled="!reviewable" :loading="saving" @click="review('reject')">拒绝投稿</NButton></NSpace>
        </template>
      </template>
    </NModal>
  </div>
</template>
<style scoped>
.submission-row { display: flex; align-items: center; gap: 20px; padding: 20px 0; border-bottom: 1px solid var(--border); }
.preview { padding: 0; border: 0; width: 100px; height: 100px; flex-shrink: 0; cursor: pointer; }
.preview :deep(.protected-image), .preview :deep(.image-placeholder) { min-height: 0; height: 100%; padding: 0; }
.submission-info { flex: 1; min-width: 0; }
.submission-info p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin: 6px 0; }
.submission-info small { display: block; color: var(--text-secondary); margin-top: 8px; }
.empty { text-align: center; padding: 60px; color: var(--text-muted); }
.review-original :deep(img) { max-height: 45vh; }
.review-prompt { white-space: pre-wrap; overflow-wrap: anywhere; }
.review-actions { margin-top: 20px; }
@media (max-width: 600px) { .submission-row { flex-wrap: wrap; gap: 12px; } .preview { width: 75px; height: 75px; } }
</style>
