<script setup lang="ts">
import { BadgeCheck, Check, Copy, Download, ExternalLink, Layers3, Share2, Sparkles, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { authState } from '@/lib/auth'
import { fetchArtwork, setFavorite, type Artwork } from '@/lib/artworks'
import { imageDownloadFilename } from '@/lib/image-download'
import type { InspirationItem } from '@/lib/types'

const props = defineProps<{
  item: InspirationItem | null
}>()

const emit = defineEmits<{
  close: []
}>()

const router = useRouter()
const open = computed(() => Boolean(props.item))
const copied = ref(false)
const shareCopied = ref(false)
const artwork = ref<Artwork | null>(null)
const saving = ref(false)
const error = ref('')
const unavailable = ref(false)
async function favorite() {
  if (!authState.token) { closeModal(); void router.push('/login'); return }
  if (!artwork.value || saving.value) return
  saving.value = true; error.value = ''
  try { artwork.value = await setFavorite(artwork.value, !artwork.value.is_favorite) }
  catch (e) { error.value = e instanceof Error ? e.message : '收藏失败。' }
  finally { saving.value = false }
}

function closeModal() {
  emit('close')
}

watch(
  () => props.item,
  async (item) => {
    copied.value = false; shareCopied.value = false; artwork.value = null; error.value = ''; unavailable.value = false
    if (item) {
      try { const result = await fetchArtwork('inspiration', item.id); if (props.item?.id === item.id) artwork.value = result }
      catch { if (props.item?.id === item.id) error.value = '作品状态读取失败，请重新打开。' }
    }
  },
  { immediate: true },
)

async function copyPrompt() {
  if (!props.item) return
  await navigator.clipboard.writeText(props.item.prompt)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1600)
}

function goToCreate() {
  if (!props.item) return
  router.push({ path: '/create', query: { prompt: props.item.prompt } })
  closeModal()
}

async function downloadImage() {
  if (!props.item || unavailable.value) return
  const item = props.item
  try {
    const response = await fetch(item.image_url)
    if (!response.ok) { if ([401,403,404,410].includes(response.status)) unavailable.value = true; throw new Error('download failed') }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = imageDownloadFilename(item.id, blob.type)
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  } catch {
    error.value = '图片暂时无法下载。'
  }
}

async function shareImage() {
  if (!props.item || unavailable.value) return
  const item = props.item
  const url = new URL(item.image_url, window.location.origin).href
  const data = { title: item.title, text: item.description || `分享灵感：${item.title}`, url }
  try {
    if (navigator.share) {
      await navigator.share(data)
      return
    }
    await navigator.clipboard.writeText(url)
    shareCopied.value = true
    window.setTimeout(() => { shareCopied.value = false }, 1600)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    error.value = '暂时无法分享，请稍后重试。'
  }
}

function formatSource(source: string) {
  if (source === 'community-curated') return '社区精选'
  if (source === 'admin-imported' || source === 'imported') return '灵感收录'
  return source
}
</script>

<template>
  <div v-if="open && item" class="modal-backdrop" @click.self="closeModal">
    <div class="modal-panel">
      <div class="modal-toolbar">
        <div class="modal-toolbar-left">
          <span class="inspiration-source-badge" :class="{ 'source-gallery': item.source === 'community-curated' }">
            <BadgeCheck v-if="item.source === 'community-curated'" :size="14" :stroke-width="1.9" aria-hidden="true" />
            <Layers3 v-else :size="14" :stroke-width="1.9" aria-hidden="true" />
            <span class="source-caption">来源</span>
            <strong>{{ formatSource(item.source) }}</strong>
          </span>
          <a
            v-if="item.source_url"
            :href="item.source_url"
            target="_blank"
            rel="noopener noreferrer"
            class="icon-button"
            title="查看来源"
            aria-label="查看来源"
          >
            <ExternalLink :size="18" />
          </a>
        </div>
        <div class="modal-toolbar-right">
          <button class="icon-button" type="button" :title="shareCopied ? '链接已复制' : '分享图片'" :aria-label="shareCopied ? '链接已复制' : '分享图片'" :disabled="unavailable" @click="shareImage">
            <Check v-if="shareCopied" :size="20" />
            <Share2 v-else :size="20" />
          </button>
          <button class="icon-button" type="button" title="下载图片" aria-label="下载图片" :disabled="unavailable" @click="downloadImage">
            <Download :size="20" />
          </button>
          <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="closeModal">
            <X :size="20" />
          </button>
        </div>
      </div>

      <div class="modal-image-frame">
        <ProtectedImage :src="item.image_url" :alt="item.title" :state="unavailable ? 'unavailable' : 'available'" eager @invalid="unavailable = true" />
      </div>

      <div class="modal-copy">
        <MediaExpiry :state="unavailable ? 'unavailable' : 'available'" permanent />
        <p v-if="error" role="alert">{{ error }}</p>
        <button class="ghost-button" :disabled="saving || (!!authState.token && !artwork) || (unavailable && !artwork?.is_favorite)" @click="favorite">{{ artwork?.is_favorite ? '取消收藏' : '收藏' }}</button>
        <h3 class="inspiration-title">{{ item.title }}</h3>

        <div v-if="item.categories && item.categories.length > 0" class="inspiration-categories">
          <span v-for="cat in item.categories" :key="cat" class="inspiration-category-tag">{{ cat }}</span>
        </div>

        <template v-if="item.prompt">
          <div class="prompt-heading">
            <p class="section-label">提示词</p>
            <div class="prompt-actions">
              <button class="copy-button" type="button" @click="copyPrompt">
                <Check v-if="copied" :size="16" />
                <Copy v-else :size="16" />
                <span>{{ copied ? '已复制' : '一键复制' }}</span>
              </button>
              <button class="create-button" type="button" @click="goToCreate">
                <Sparkles :size="16" />
                <span>去创作</span>
              </button>
            </div>
          </div>
          <p class="modal-prompt">{{ item.prompt }}</p>
        </template>
        <template v-else-if="item.source === 'community-curated'">
          <p class="modal-prompt-hidden">提示词已隐藏</p>
        </template>

        <p v-if="item.description" class="section-label">描述</p>
        <p v-if="item.description" class="modal-description">{{ item.description }}</p>

        <div class="modal-meta">
          <span v-if="item.author_name">{{ item.author_name }}</span>
          <span>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</span>
          <span v-if="item.language">{{ item.language }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inspiration-source-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 4px 9px 4px 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 12px;
}

.inspiration-source-badge.source-gallery {
  border-color: var(--border-accent);
  background: var(--accent-glow);
  color: var(--accent-strong);
}

.inspiration-source-badge strong {
  color: var(--text-primary);
  font-weight: 650;
}

.source-caption {
  padding-right: 6px;
  border-right: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.inspiration-title {
  margin: 0 0 12px;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.4;
}

.prompt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.create-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--accent);
  color: var(--accent-foreground);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s ease;
  min-height: 28px;
}

.create-button:hover {
  opacity: 0.9;
}

.modal-description {
  margin: 0 0 16px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.inspiration-categories {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.inspiration-category-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  background: var(--accent);
  color: var(--accent-foreground, #fff);
  font-size: 12px;
  font-weight: 500;
  opacity: 0.85;
}

.modal-prompt-hidden {
  padding: 16px 0;
  color: var(--text-secondary);
  font-size: 14px;
  font-style: italic;
}
</style>
