<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ArtworkCard from '@/components/ArtworkCard.vue'
import ArtworkModal from '@/components/ArtworkModal.vue'
import { authState, fetchCurrentUser } from '@/lib/auth'
import { clearInvalidFavorites, fetchArtwork, fetchArtworkPage, setFavorite, type Artwork } from '@/lib/artworks'
import { syncMediaClock, useMediaClock } from '@/composables/useMediaClock'
import { mediaAvailable } from '@/lib/media-state'

const props = defineProps<{ mode: 'history' | 'gallery' | 'favorites' }>()
const route = useRoute(), router = useRouter()
const now = useMediaClock()
const items = ref<Artwork[]>([])
const total = ref(0), page = ref(1)
const loading = ref(true), busy = ref(new Set<string>())
const error = ref(''), notice = ref('')
const state = ref('all'), query = ref(''), fromDate = ref(''), toDate = ref('')
const selected = ref<Artwork | null>(null)
const username = computed(() => String(route.params.username || authState.user?.username || ''))
const ownGallery = computed(() => props.mode === 'gallery' && username.value === authState.user?.username)
const title = computed(() => props.mode === 'history' ? '生图历史' : props.mode === 'favorites' ? '收藏' : ownGallery.value ? '我的画廊' : `${username.value} 的画廊`)
const visibleItems = computed(() => props.mode === 'gallery' ? items.value.filter(i => mediaAvailable(i.media_state, i.media_expires_at, now.value)) : items.value)
const tabs = computed(() => props.mode === 'history' ? [
  ['all','全部'], ['processing','生成中'], ['queued','排队中'], ['succeeded','成功'], ['failed','失败'], ['expired','图片已过期'],
] : [['all','全部'],['available','可用'],['unavailable','失效']])
let controller: AbortController | undefined
let poll: ReturnType<typeof setTimeout> | undefined
let requestId = 0
const refreshed = new Set<string>()

async function load(nextPage = 1, quiet = false) {
  const id = ++requestId
  controller?.abort(); controller = new AbortController()
  if (poll) clearTimeout(poll)
  error.value = ''
  if (!quiet) loading.value = true
  try {
    if (props.mode === 'gallery' && !route.params.username && !authState.user) await fetchCurrentUser()
    if (id !== requestId) return
    const path = props.mode === 'gallery' ? `portfolios/${encodeURIComponent(username.value)}` : props.mode
    const params: Record<string,string|number> = { page: nextPage, page_size: 20 }
    if (props.mode !== 'gallery') params.state = state.value
    if (props.mode === 'history') {
      params.q = query.value
      if (fromDate.value) params.from_date = new Date(`${fromDate.value}T00:00:00`).toISOString()
      if (toDate.value) params.to_date = new Date(`${toDate.value}T00:00:00`).toISOString()
    }
    const result = await fetchArtworkPage(path, params, controller.signal)
    if (id !== requestId) return
    items.value = result.items; total.value = result.total; page.value = result.page
    syncMediaClock(result.server_time)
    if (props.mode === 'history' && result.items.some(i => ['queued','processing'].includes(i.status || ''))) {
      poll = setTimeout(() => { void load(page.value, true) }, 10000)
    }
  } catch (e) {
    if (id === requestId && !(e instanceof DOMException && e.name === 'AbortError')) error.value = e instanceof Error ? e.message : '加载失败。'
  } finally { if (id === requestId) loading.value = false }
}
function update(item: Artwork) {
  const index = items.value.findIndex(i => i.kind === item.kind && i.id === item.id)
  if (index >= 0) items.value.splice(index, 1, item)
  if (selected.value?.id === item.id && selected.value.kind === item.kind) selected.value = item
  if ((props.mode === 'favorites' && !item.is_favorite) || (props.mode === 'gallery' && !item.is_in_gallery)) {
    items.value = items.value.filter(i => !(i.kind === item.kind && i.id === item.id)); total.value = Math.max(0, total.value - 1)
  }
}
async function favorite(item: Artwork) {
  if (!authState.token) { void router.push('/login'); return }
  busy.value = new Set(busy.value).add(item.id)
  try { update(await setFavorite(item, !item.is_favorite)) }
  catch (e) { error.value = e instanceof Error ? e.message : '收藏失败。' }
  finally { const next = new Set(busy.value); next.delete(item.id); busy.value = next }
}
async function refreshItem(item: Artwork) {
  const key = `${item.kind}:${item.id}`
  if (refreshed.has(key)) return
  refreshed.add(key)
  try { update(await fetchArtwork(item.kind, item.id)) }
  catch { /* Image remains a failed placeholder; never reload every card. */ }
}
async function clearInvalid() {
  if (!confirm('清理全部已失效的收藏引用？不会删除任何原作品。')) return
  try { const result = await clearInvalidFavorites(); notice.value = `已清理 ${result.removed} 条失效收藏`; await load(1) }
  catch (e) { error.value = e instanceof Error ? e.message : '清理失败。' }
}
async function share() {
  try { await navigator.clipboard.writeText(`${location.origin}/gallery/${encodeURIComponent(username.value)}`); notice.value = '画廊链接已复制' }
  catch { notice.value = `分享地址：${location.origin}/gallery/${encodeURIComponent(username.value)}` }
}
function deleted(item: Artwork) {
  items.value = items.value.filter(i => !(i.kind === item.kind && i.id === item.id)); total.value = Math.max(0,total.value-1)
}
watch([() => props.mode, () => route.params.username, () => authState.token], () => {
  state.value = 'all'; selected.value = null; refreshed.clear(); items.value = []; void load(1)
}, { immediate: true })
onBeforeUnmount(() => { requestId += 1; controller?.abort(); if (poll) clearTimeout(poll) })
</script>
<template>
  <section class="artwork-library">
    <header class="library-heading">
      <div><p class="library-kicker">{{ mode === 'history' ? '创作记录' : mode === 'favorites' ? '我的收藏' : '个人作品集' }}</p><h1>{{ title }}</h1>
      <p>{{ mode === 'history' ? '每一次创作都在这里。图片到期后，提示词和生成记录继续保留。' : mode === 'favorites' ? '收藏喜欢的作品，不会延长原图保存时间。收录版可长期查看。' : '这里展示主动加入画廊的作品；是否公开由个人中心总开关控制。' }}</p></div>
      <button v-if="ownGallery" class="ghost-button" @click="share">复制画廊链接</button>
      <router-link v-if="mode === 'history'" class="primary-button" to="/create">开始创作</router-link>
    </header>
    <aside v-if="ownGallery && !authState.user?.is_public" class="library-notice">画廊尚未公开，目前只有你能看到。<router-link to="/profile">前往个人中心开启公开总开关</router-link></aside>
    <p v-if="error" class="feedback-banner" role="alert">{{ error }} <button class="ghost-button" @click="load(page)">重新加载</button></p>
    <p v-if="notice" class="library-notice" role="status">{{ notice }}</p>
    <div v-if="mode !== 'gallery'" class="library-toolbar">
      <div class="library-tabs" aria-label="筛选记录"><button v-for="[value,label] in tabs" :key="value" :aria-pressed="state === value" @click="state = value; load(1)">{{ label }}</button></div>
      <button v-if="mode === 'favorites'" class="ghost-button" @click="clearInvalid">清理失效收藏</button>
    </div>
    <form v-if="mode === 'history'" class="history-search" @submit.prevent="load(1)">
      <input v-model="query" type="search" placeholder="搜索提示词" aria-label="搜索提示词" maxlength="200" />
      <input v-model="fromDate" type="date" aria-label="开始日期" /><span>至</span><input v-model="toDate" type="date" aria-label="结束日期" />
      <button class="ghost-button">筛选</button><button type="button" class="ghost-button" @click="query = ''; fromDate = ''; toDate = ''; state = 'all'; load(1)">重置</button>
    </form>
    <div class="library-count">{{ total }} 条{{ mode === 'history' ? '记录' : '作品' }}<span v-if="loading"> · 正在加载…</span></div>
    <div v-if="visibleItems.length" class="artwork-grid" :aria-busy="loading"><ArtworkCard v-for="item in visibleItems" :key="`${item.kind}:${item.id}`" :item="item" :busy="busy.has(item.id)" @select="selected = item" @favorite="favorite(item)" @invalid="refreshItem(item)" /></div>
    <div v-else-if="!loading && !error" class="library-empty"><h2>{{ mode === 'history' ? '还没有符合条件的生成记录' : mode === 'gallery' ? '画廊还没有作品' : '这里还没有收藏' }}</h2><p>{{ mode === 'gallery' ? '从生图历史打开作品详情，点击“加入画廊”。' : mode === 'favorites' ? '在个人画廊、历史或社区灵感中点击“收藏”。' : '试试放宽筛选条件，或开始一次新的创作。' }}</p><router-link :to="mode === 'gallery' ? '/history' : mode === 'favorites' ? '/' : '/create'">{{ mode === 'gallery' ? '查看生图历史' : mode === 'favorites' ? '探索社区灵感' : '前往创作台' }}</router-link></div>
    <nav v-if="total > 20" class="gallery-pagination" aria-label="列表分页"><button class="ghost-button" :disabled="loading || page <= 1" @click="load(page - 1)">上一页</button><span>{{ page }} / {{ Math.ceil(total / 20) }}</span><button class="ghost-button" :disabled="loading || page >= Math.ceil(total / 20)" @click="load(page + 1)">下一页</button></nav>
    <ArtworkModal v-if="selected" :key="`${selected.kind}:${selected.id}`" :item="selected" @close="selected = null" @updated="update" @deleted="deleted" @invalid="refreshItem(selected)" />
  </section>
</template>
<style scoped>
.artwork-library { max-width: 1200px; margin: 0 auto; padding: 24px 0 48px; }
.library-heading { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.library-heading h1 { margin: 4px 0 12px; font-size: 32px; font-weight: 600; }
.library-heading p { margin: 0; color: var(--text-secondary); line-height: 1.7; }
.library-heading .library-kicker { color: var(--accent); font-size: 12px; letter-spacing: 0.08em; }
.library-heading > button, .library-heading > a { flex-shrink: 0; text-decoration: none; }
.library-notice { padding: 12px 16px; background: var(--accent-glow); border: 1px solid var(--border-accent); border-radius: var(--radius-sm); line-height: 1.7; font-size: 14px; }
.library-toolbar { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin: 24px 0 16px; }
.library-tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.library-tabs button { background: none; color: var(--text-secondary); border: 1px solid var(--border); padding: 8px 14px; border-radius: var(--radius-sm); cursor: pointer; font: inherit; font-size: 14px; }
.library-tabs button[aria-pressed='true'] { background: var(--accent-glow); color: var(--accent); border-color: var(--border-accent); }
.history-search { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.history-search input { border: 1px solid var(--border); padding: 10px 12px; border-radius: var(--radius-sm); background: var(--bg-input); color: var(--text-primary); font: inherit; font-size: 14px; }
.history-search input[type='search'] { flex: 1; min-width: 160px; }
.library-count { margin: 24px 0 16px; color: var(--text-muted); font-size: 13px; }
.artwork-grid { columns: 4; column-gap: 24px; }
.library-empty { padding: 64px 24px; text-align: center; border: 1px solid var(--border); border-radius: var(--radius-md); }
.library-empty h2 { font-size: 20px; }.library-empty p { color: var(--text-secondary); line-height: 1.8; }
@media (max-width: 1100px) { .artwork-grid { columns: 3; } }
@media (max-width: 767px) { .artwork-grid { columns: 2; column-gap: 16px; }.library-heading { align-items: flex-start; flex-wrap: wrap; }.library-heading h1 { font-size: 28px; } }
@media (max-width: 420px) { .artwork-grid { columns: 1; } }
</style>
