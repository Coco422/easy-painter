<script setup lang="ts">
import { Check, Copy, Download, ExternalLink, Sparkles, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

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

function closeModal() {
  emit('close')
}

watch(
  () => props.item,
  () => {
    copied.value = false
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

function goToCreate() {
  if (!props.item) return
  router.push({ path: '/create', query: { prompt: props.item.prompt } })
  closeModal()
}

async function downloadImage() {
  if (!props.item) return
  const filename = props.item.image_url.split('/').pop() || `${props.item.id}.png`
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

function formatSource(source: string) {
  if (source === 'gallery') return '社区作品'
  return source
}
</script>

<template>
  <div v-if="open && item" class="modal-backdrop" @click.self="closeModal">
    <div class="modal-panel">
      <div class="modal-toolbar">
        <div class="modal-toolbar-left">
          <span class="inspiration-source-badge" :class="{ 'source-gallery': item.source === 'gallery' }">
            {{ formatSource(item.source) }}
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
          <button class="icon-button" type="button" title="下载图片" aria-label="下载图片" @click="downloadImage">
            <Download :size="20" />
          </button>
          <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="closeModal">
            <X :size="20" />
          </button>
        </div>
      </div>

      <div class="modal-image-frame">
        <img :src="item.image_url" :alt="item.title" class="modal-image" />
      </div>

      <div class="modal-copy">
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
        <template v-else-if="item.source === 'gallery'">
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
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(168, 85, 247, 0.15);
  color: #a855f7;
}

.inspiration-source-badge.source-gallery {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
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
