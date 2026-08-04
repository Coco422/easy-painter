<script setup lang="ts">
import { ImagePlus, Loader2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { useReferenceImages } from '@/composables/useReferenceImages'
import type { ReferenceImageItem } from '@/lib/types'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  select: [item: ReferenceImageItem]
}>()

const {
  selected,
  uploading,
  history,
  historyLoading,
  pendingPreviewUrl,
  pendingFilename,
  deletingIds,
  getObjectUrl,
  remove,
  loadHistory,
} = useReferenceImages()

const loadError = ref('')
const hasItems = computed(() => uploading.value || history.value.length > 0)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    loadError.value = ''
    try {
      await loadHistory()
    } catch (error) {
      loadError.value = error instanceof Error ? error.message : '参考图历史加载失败，请稍后重试。'
    }
  },
)

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) close()
}

document.addEventListener('keydown', handleKeydown)
onBeforeUnmount(() => document.removeEventListener('keydown', handleKeydown))

function close() {
  emit('update:open', false)
}

function handleSelect(item: ReferenceImageItem) {
  emit('select', item)
  close()
}

function handleItemKeydown(event: KeyboardEvent, item: ReferenceImageItem) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  handleSelect(item)
}

async function handleRemove(item: ReferenceImageItem) {
  loadError.value = ''
  try {
    await remove(item)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '删除参考图失败，请稍后重试。'
  }
}
</script>

<template>
  <Transition name="reference-drawer">
    <div v-if="open" class="reference-drawer">
      <div class="reference-drawer-backdrop" @click="close" />
      <aside class="reference-drawer-panel" role="dialog" aria-modal="true" aria-label="参考图历史">
        <header class="reference-drawer-header">
          <h3 class="reference-drawer-title">参考图历史</h3>
          <button type="button" class="icon-button" title="关闭" aria-label="关闭" @click="close">
            <X :size="18" />
          </button>
        </header>
        <div class="reference-drawer-body">
          <p v-if="loadError" class="reference-drawer-error">{{ loadError }}</p>
          <div v-if="historyLoading && !hasItems" class="reference-drawer-loading">
            <Loader2 :size="22" />
            <span>正在读取参考图历史…</span>
          </div>
          <p v-else-if="!hasItems" class="reference-drawer-empty">
            还没有参考图，粘贴或拖入图片即可上传
          </p>
          <div v-else class="reference-drawer-grid">
            <div v-if="uploading" class="reference-drawer-item pending" aria-label="参考图上传中">
              <img v-if="pendingPreviewUrl" :src="pendingPreviewUrl" :alt="pendingFilename" />
              <span v-else class="reference-drawer-placeholder"><ImagePlus :size="24" /></span>
              <span class="reference-drawer-pending"><Loader2 :size="16" /> 上传中</span>
            </div>
            <div
              v-for="item in history"
              :key="item.id"
              class="reference-drawer-item"
              :class="{ selected: selected?.id === item.id }"
              role="button"
              tabindex="0"
              :title="item.filename"
              @click="handleSelect(item)"
              @keydown="handleItemKeydown($event, item)"
            >
              <img v-if="getObjectUrl(item.id)" :src="getObjectUrl(item.id)" :alt="item.filename" loading="lazy" />
              <span v-else class="reference-drawer-placeholder"><Loader2 :size="20" /></span>
              <span v-if="item.used_count > 0" class="reference-drawer-badge">用过 {{ item.used_count }} 次</span>
              <button
                type="button"
                class="reference-drawer-delete"
                title="删除参考图"
                aria-label="删除参考图"
                :disabled="deletingIds.has(item.id)"
                @click.stop="handleRemove(item)"
              >
                <Loader2 v-if="deletingIds.has(item.id)" :size="14" />
                <X v-else :size="14" />
              </button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </Transition>
</template>
