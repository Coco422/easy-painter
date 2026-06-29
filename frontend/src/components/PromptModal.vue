<script setup lang="ts">
import { Check, Copy, Download, Globe, Lock, Sparkles, Star, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import type { GalleryItem } from '@/lib/types'

const DEFAULT_TAGS = ['头像', '插画', '海报', '风景', '人像', '动漫', '3D', 'LOGO', '表情包', '壁纸']

const props = defineProps<{
  item: GalleryItem | null
  isOwner?: boolean
  popularTags?: string[]
}>()

const emit = defineEmits<{
  close: []
  toggleFavorite: [item: GalleryItem]
  publish: [item: GalleryItem, tags: string[], isPromptPublic: boolean]
  unpublish: [item: GalleryItem]
}>()

const router = useRouter()
const open = computed(() => Boolean(props.item))
const copied = ref(false)
const publishMode = ref(false)
const selectedTags = ref<string[]>([])
const customTagInput = ref('')
const isPromptPublic = ref(true)
const MAX_TAGS = 5

const availableTags = computed(() => {
  const tags = props.popularTags && props.popularTags.length > 0 ? props.popularTags : DEFAULT_TAGS
  return tags.filter(t => !selectedTags.value.includes(t))
})

function closeModal() {
  publishMode.value = false
  emit('close')
}

function enterPublishMode() {
  publishMode.value = true
  selectedTags.value = []
  customTagInput.value = ''
  isPromptPublic.value = true
}

function cancelPublish() {
  publishMode.value = false
}

function toggleTag(tag: string) {
  const idx = selectedTags.value.indexOf(tag)
  if (idx >= 0) {
    selectedTags.value.splice(idx, 1)
  } else if (selectedTags.value.length < MAX_TAGS) {
    selectedTags.value.push(tag)
  }
}

function addCustomTag() {
  const tag = customTagInput.value.trim()
  if (!tag || selectedTags.value.includes(tag) || selectedTags.value.length >= MAX_TAGS) return
  selectedTags.value.push(tag)
  customTagInput.value = ''
}

function removeTag(tag: string) {
  selectedTags.value = selectedTags.value.filter(t => t !== tag)
}

function confirmPublish() {
  if (!props.item) return
  emit('publish', props.item, selectedTags.value, isPromptPublic.value)
}

function handlePublicToggle() {
  if (!props.item) return
  if (props.item.is_public) {
    emit('unpublish', props.item)
  } else {
    enterPublishMode()
  }
}

watch(
  () => props.item,
  () => {
    copied.value = false
    publishMode.value = false
  },
)

async function copyPrompt() {
  if (!props.item) return
  await navigator.clipboard.writeText(props.item.prompt)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1600)
}

async function downloadImage() {
  if (!props.item) return
  const filename = props.item.image_url.split('/').pop() || `${props.item.job_id}.png`
  try {
    const response = await fetch(props.item.image_url)
    if (!response.ok) throw new Error('download failed')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  } catch {
    window.open(props.item.image_url, '_blank', 'noopener,noreferrer')
  }
}

function goToCreate() {
  if (!props.item) return
  router.push({ path: '/create', query: { prompt: props.item.prompt } })
}

function onCustomTagKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    addCustomTag()
  }
}
</script>

<template>
  <div v-if="open && item" class="modal-backdrop" @click.self="closeModal">
    <div class="modal-panel">
      <div class="modal-toolbar" :class="{ 'modal-toolbar--owner': isOwner }">
        <div v-if="isOwner" class="modal-toolbar-left">
          <button
            class="icon-button"
            :class="{ active: item.is_favorite }"
            type="button"
            title="收藏"
            aria-label="收藏"
            @click="emit('toggleFavorite', item)"
          >
            <Star :size="20" :fill="item.is_favorite ? 'currentColor' : 'none'" />
          </button>
          <button
            class="icon-button"
            :class="{ active: item.is_public }"
            type="button"
            :title="item.is_public ? '公开' : '私密'"
            :aria-label="item.is_public ? '公开' : '私密'"
            @click="handlePublicToggle"
          >
            <Globe v-if="item.is_public" :size="20" />
            <Lock v-else :size="20" />
          </button>
        </div>
        <div class="modal-toolbar-right">
          <button class="icon-button" type="button" title="下载图片" aria-label="下载图片" @click="downloadImage">
            <Download :size="20" />
          </button>
          <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="closeModal">
            <X :size="20" />
          </button>
        </div>
      </div>

      <div class="modal-image-frame">
        <img :src="item.image_url" :alt="item.prompt" class="modal-image" />
      </div>

      <!-- Publish mode: tag input -->
      <div v-if="publishMode" class="publish-panel">
        <h3 class="publish-title">发布到社区</h3>
        <p class="publish-desc">选择标签，让更多人发现你的作品</p>

        <div class="publish-tags-section">
          <p class="publish-section-label">热门标签</p>
          <div class="publish-tag-suggestions">
            <button
              v-for="tag in availableTags.slice(0, 10)"
              :key="tag"
              class="publish-tag-btn"
              type="button"
              @click="toggleTag(tag)"
            >{{ tag }}</button>
          </div>
        </div>

        <div class="publish-tags-section">
          <p class="publish-section-label">自定义标签</p>
          <div class="publish-custom-input-row">
            <input
              v-model="customTagInput"
              type="text"
              class="publish-custom-input"
              placeholder="输入标签名称..."
              maxlength="20"
              @keydown="onCustomTagKeydown"
            />
            <button
              class="publish-add-btn"
              type="button"
              :disabled="!customTagInput.trim() || selectedTags.length >= MAX_TAGS"
              @click="addCustomTag"
            >添加</button>
          </div>
        </div>

        <div v-if="selectedTags.length > 0" class="publish-tags-section">
          <p class="publish-section-label">已选标签 ({{ selectedTags.length }}/{{ MAX_TAGS }})</p>
          <div class="publish-selected-tags">
            <span v-for="tag in selectedTags" :key="tag" class="publish-selected-tag">
              {{ tag }}
              <button class="publish-tag-remove" type="button" @click="removeTag(tag)">&times;</button>
            </span>
          </div>
        </div>

        <div class="publish-option-row">
          <label class="publish-toggle-label">
            <input v-model="isPromptPublic" type="checkbox" class="publish-toggle-checkbox" />
            <span class="publish-toggle-text">公开提示词</span>
          </label>
          <span class="publish-toggle-hint">{{ isPromptPublic ? '其他用户可以复制你的提示词' : '提示词将对其他用户隐藏' }}</span>
        </div>

        <div class="publish-actions">
          <button class="publish-cancel-btn" type="button" @click="cancelPublish">取消</button>
          <button class="publish-confirm-btn" type="button" @click="confirmPublish">发布</button>
        </div>
      </div>

      <!-- Normal mode: prompt display -->
      <div v-else class="modal-copy">
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
        <template v-if="item.is_prompt_public === false && item.is_public">
          <p class="modal-prompt-hidden">提示词已隐藏</p>
        </template>
        <template v-else>
          <p class="modal-prompt">{{ item.prompt }}</p>
        </template>

        <template v-if="item.revised_prompt">
          <p class="section-label">模型修订提示词</p>
          <p class="modal-revised">{{ item.revised_prompt }}</p>
        </template>

        <div v-if="item.tags && item.tags.length > 0" class="modal-tags">
          <span v-for="tag in item.tags" :key="tag" class="modal-tag">{{ tag }}</span>
        </div>

        <div class="modal-meta">
          <span>{{ item.model }}</span>
          <span>{{ new Date(item.finished_at).toLocaleString('zh-CN') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
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

/* Publish panel */
.publish-panel {
  padding: 16px 20px 20px;
}

.publish-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}

.publish-desc {
  margin: 4px 0 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

.publish-tags-section {
  margin-bottom: 14px;
}

.publish-section-label {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.publish-tag-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.publish-tag-btn {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 150ms;
}

.publish-tag-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.publish-custom-input-row {
  display: flex;
  gap: 8px;
}

.publish-custom-input {
  flex: 1;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  background: var(--bg-card);
  color: var(--text);
  font-size: 13px;
  outline: none;
}

.publish-custom-input:focus {
  border-color: var(--accent);
}

.publish-add-btn {
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 150ms;
}

.publish-add-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.publish-add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.publish-selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.publish-selected-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 14px;
  background: var(--accent);
  color: var(--accent-foreground, #fff);
  font-size: 13px;
  font-weight: 500;
}

.publish-tag-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: none;
  background: transparent;
  color: inherit;
  font-size: 14px;
  cursor: pointer;
  opacity: 0.8;
  padding: 0;
  line-height: 1;
}

.publish-tag-remove:hover {
  opacity: 1;
}

.publish-option-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
}

.publish-toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  flex-shrink: 0;
}

.publish-toggle-checkbox {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}

.publish-toggle-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
}

.publish-toggle-hint {
  font-size: 12px;
  color: var(--text-secondary);
}

.publish-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.publish-cancel-btn {
  padding: 8px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 150ms;
}

.publish-cancel-btn:hover {
  color: var(--text);
}

.publish-confirm-btn {
  padding: 8px 24px;
  border: none;
  border-radius: var(--radius-sm, 6px);
  background: var(--accent);
  color: var(--accent-foreground, #fff);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 150ms;
}

.publish-confirm-btn:hover {
  opacity: 0.9;
}

/* Tags display in normal mode */
.modal-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.modal-tag {
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
