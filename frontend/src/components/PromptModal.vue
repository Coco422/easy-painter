<script setup lang="ts">
import { Check, Copy, Download, Globe, Lock, Star, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import type { GalleryItem } from '@/lib/types'

const props = defineProps<{
  item: GalleryItem | null
  isOwner?: boolean
}>()

const emit = defineEmits<{
  close: []
  toggleFavorite: [item: GalleryItem]
  togglePublic: [item: GalleryItem]
}>()

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
            @click="emit('togglePublic', item)"
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
      <div class="modal-copy">
        <div class="prompt-heading">
          <p class="section-label">提示词</p>
          <button class="copy-button" type="button" @click="copyPrompt">
            <Check v-if="copied" :size="16" />
            <Copy v-else :size="16" />
            <span>{{ copied ? '已复制' : '一键复制' }}</span>
          </button>
        </div>
        <p class="modal-prompt">{{ item.prompt }}</p>

        <template v-if="item.revised_prompt">
          <p class="section-label">模型修订提示词</p>
          <p class="modal-revised">{{ item.revised_prompt }}</p>
        </template>

        <div class="modal-meta">
          <span>{{ item.model }}</span>
          <span>{{ new Date(item.finished_at).toLocaleString('zh-CN') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
