import { reactive, ref, watch } from 'vue'

import {
  deleteReferenceImage,
  fetchReferenceImageObjectUrl,
  fetchReferenceImages,
  uploadReferenceImage,
} from '@/lib/api'
import { authState } from '@/lib/auth'
import type { ReferenceImageItem } from '@/lib/types'

// 模块级单例：GeneratePanel 与历史抽屉、CreatePage 共享同一份状态。
const selected = ref<ReferenceImageItem[]>([])
const uploading = ref(false)
const history = ref<ReferenceImageItem[]>([])
const historyLoading = ref(false)
const historyPage = ref(1)
const historyTotal = ref(0)
const pendingPreviewUrl = ref<string | null>(null)
const pendingFilename = ref('')

const objectUrls = reactive(new Map<string, string>())
const pendingObjectUrls = new Set<string>()
const deletingIds = reactive(new Set<string>())
let objectUrlGeneration = 0

function getObjectUrl(id: string): string | undefined {
  const cached = objectUrls.get(id)
  if (cached) return cached
  if (pendingObjectUrls.has(id)) return undefined
  pendingObjectUrls.add(id)
  const generation = objectUrlGeneration
  void fetchReferenceImageObjectUrl(id)
    .then((url) => {
      if (generation !== objectUrlGeneration) {
        URL.revokeObjectURL(url)
        return
      }
      objectUrls.set(id, url)
    })
    .catch(() => {})
    .finally(() => {
      pendingObjectUrls.delete(id)
    })
  return undefined
}

function releaseObjectUrls() {
  objectUrlGeneration += 1
  for (const url of objectUrls.values()) {
    URL.revokeObjectURL(url)
  }
  objectUrls.clear()
  if (pendingPreviewUrl.value) {
    URL.revokeObjectURL(pendingPreviewUrl.value)
    pendingPreviewUrl.value = null
  }
}

function releaseObjectUrl(id: string) {
  const url = objectUrls.get(id)
  if (!url) return
  URL.revokeObjectURL(url)
  objectUrls.delete(id)
}

async function uploadAndSelect(file: File, confirmEvictOldest: boolean, limit: number) {
  if (selected.value.length >= limit) throw new Error(`当前模型单次最多支持 ${limit} 张参考图。`)
  const ownerToken = authState.token
  if (uploading.value) {
    throw new Error('已有参考图正在上传，请稍候。')
  }
  uploading.value = true
  pendingFilename.value = file.name
  pendingPreviewUrl.value = URL.createObjectURL(file)
  try {
    const item = await uploadReferenceImage(file, confirmEvictOldest)
    if (ownerToken !== authState.token) throw new Error('登录状态已变化，请重新选择参考图。')
    for (const id of item.evicted_image_ids ?? []) {
      deselect(id)
      releaseObjectUrl(id)
    }
    const previewUrl = pendingPreviewUrl.value
    if (previewUrl) {
      const previousUrl = objectUrls.get(item.id)
      if (previousUrl && previousUrl !== previewUrl) URL.revokeObjectURL(previousUrl)
      objectUrls.set(item.id, previewUrl)
      pendingPreviewUrl.value = null
    }
    select(item, limit)
    const evictedIds = new Set(item.evicted_image_ids ?? [])
    history.value = [item, ...history.value.filter((entry) => entry.id !== item.id && !evictedIds.has(entry.id))]
    await loadHistory().catch(() => undefined)
    return item
  } finally {
    if (pendingPreviewUrl.value) {
      URL.revokeObjectURL(pendingPreviewUrl.value)
      pendingPreviewUrl.value = null
    }
    pendingFilename.value = ''
    uploading.value = false
  }
}

function select(item: ReferenceImageItem, limit: number) {
  if (selected.value.some((entry) => entry.id === item.id)) return
  if (selected.value.length >= limit) throw new Error(`当前模型单次最多支持 ${limit} 张参考图。`)
  selected.value = [...selected.value, item]
}

function deselect(id: string) {
  selected.value = selected.value.filter((item) => item.id !== id)
}

function clearSelected() {
  selected.value = []
}

watch(() => authState.token, () => {
  clearSelected()
  history.value = []
  historyTotal.value = 0
  releaseObjectUrls()
})

async function remove(item: ReferenceImageItem) {
  if (deletingIds.has(item.id)) return
  deletingIds.add(item.id)
  try {
    await deleteReferenceImage(item.id)
    history.value = history.value.filter((entry) => entry.id !== item.id)
    historyTotal.value = Math.max(0, historyTotal.value - 1)
    deselect(item.id)
    releaseObjectUrl(item.id)
  } finally {
    deletingIds.delete(item.id)
  }
}

async function loadHistory(reset = true) {
  const ownerToken = authState.token
  historyLoading.value = true
  try {
    const nextPage = reset ? 1 : historyPage.value + 1
    const response = await fetchReferenceImages(nextPage)
    if (ownerToken !== authState.token) return
    history.value = reset
      ? response.items
      : [...history.value, ...response.items.filter((item) => !history.value.some((entry) => entry.id === item.id))]
    historyPage.value = response.page
    historyTotal.value = response.total
  } finally {
    historyLoading.value = false
  }
}

export function useReferenceImages() {
  return {
    selected,
    uploading,
    history,
    historyLoading,
    historyTotal,
    pendingPreviewUrl,
    pendingFilename,
    deletingIds,
    getObjectUrl,
    releaseObjectUrls,
    uploadAndSelect,
    select,
    clearSelected,
    deselect,
    remove,
    loadHistory,
  }
}
