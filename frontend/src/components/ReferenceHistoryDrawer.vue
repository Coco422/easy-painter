<script setup lang="ts">
import { ImagePlus, Loader2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { authState } from '@/lib/auth'
import { useReferenceImages } from '@/composables/useReferenceImages'
import type { ReferenceImageItem } from '@/lib/types'

const props = defineProps<{
  open: boolean
  selectionLimit: number
  selectionDisabled: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  select: [item: ReferenceImageItem]
}>()

const {
  selected,
  deselect,
  uploading,
  history,
  historyLoading,
  historyTotal,
  pendingPreviewUrl,
  pendingFilename,
  deletingIds,
  getObjectUrl,
  remove,
  loadHistory,
} = useReferenceImages()

const loadError = ref('')
const hasItems = computed(() => uploading.value || history.value.length > 0)
const referenceLimit = computed(() => authState.user?.group?.max_reference_images)

function formatExpiry(value: string | null | undefined) {
  return value ? `到期：${new Date(value).toLocaleString()}` : '长期保留'
}

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
  if (props.selectionDisabled) return
  loadError.value = ''
  if (selected.value.some((entry) => entry.id === item.id)) deselect(item.id)
  else if (selected.value.length < props.selectionLimit) emit('select', item)
  else loadError.value = `当前模型单次最多支持 ${props.selectionLimit} 张参考图，请先取消一张。`
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
          <p class="reference-drawer-hint">
            当前组最多保留 {{ referenceLimit ?? '—' }} 张；达到上限时上传会先征求确认，再淘汰最早的图片。创作框中的 × 只取消本次使用。
          </p>
          <p class="reference-drawer-hint">本次已选 {{ selected.length }} / {{ selectionLimit }} 张；点击图片可选择或取消。</p>
          <p v-if="loadError" class="reference-drawer-error">{{ loadError }}</p>
          <div v-if="historyLoading && !hasItems" class="reference-drawer-loading">
            <Loader2 :size="22" />
            <span>正在读取参考图历史…</span>
          </div>
          <p v-else-if="!hasItems" class="reference-drawer-empty">
            还没有参考图，点击上传、粘贴或拖入图片后会保存在这里
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
              :class="{ selected: selected.some((entry) => entry.id === item.id) }"
              role="button"
              tabindex="0"
              :title="item.filename"
              :aria-pressed="selected.some((entry) => entry.id === item.id)"
              :aria-disabled="selectionDisabled"
              :data-selection-full="!selected.some((entry) => entry.id === item.id) && selected.length >= selectionLimit"
              @click="handleSelect(item)"
              @keydown="handleItemKeydown($event, item)"
            >
              <img v-if="getObjectUrl(item.id)" :src="getObjectUrl(item.id)" :alt="item.filename" loading="lazy" />
              <span v-else class="reference-drawer-placeholder"><Loader2 :size="20" /></span>
              <span v-if="item.used_count > 0" class="reference-drawer-badge">用过 {{ item.used_count }} 次</span>
              <span class="reference-drawer-expiry">{{ formatExpiry(item.media_expires_at) }}</span>
              <button
                type="button"
                class="reference-drawer-delete"
                title="删除参考图"
                aria-label="删除参考图"
                :disabled="selectionDisabled || deletingIds.has(item.id)"
                @click.stop="handleRemove(item)"
              >
                <Loader2 v-if="deletingIds.has(item.id)" :size="14" />
                <X v-else :size="14" />
              </button>
            </div>
          </div>
          <button
            v-if="history.length < historyTotal"
            type="button"
            class="ghost-button reference-load-more"
            :disabled="historyLoading"
            @click="loadHistory(false)"
          >
            {{ historyLoading ? '正在加载…' : `加载更多（${history.length} / ${historyTotal}）` }}
          </button>
        </div>
      </aside>
    </div>
  </Transition>
</template>

<style scoped>
.reference-drawer-expiry { position: absolute; right: 6px; bottom: 6px; max-width: calc(100% - 12px); overflow: hidden; color: #fff; font-size: 10px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; text-shadow: 0 1px 2px rgba(0, 0, 0, .85); }
.reference-load-more { width: 100%; margin-top: 12px; }
</style>
