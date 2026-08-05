import { reactive, ref } from 'vue'

import {
  deleteReferenceImage,
  fetchReferenceImageObjectUrl,
  fetchReferenceImages,
  uploadReferenceImage,
} from '@/lib/api'
import type { ReferenceImageItem } from '@/lib/types'

// 模块级单例：GeneratePanel 与历史抽屉、CreatePage 共享同一份状态。
const MAX_REFERENCE_HISTORY = 50
const selected = ref<ReferenceImageItem | null>(null)
const uploading = ref(false)
const history = ref<ReferenceImageItem[]>([])
const historyLoading = ref(false)
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

async function uploadAndSelect(file: File) {
  if (uploading.value) {
    throw new Error('已有参考图正在上传，请稍候。')
  }
  uploading.value = true
  pendingFilename.value = file.name
  pendingPreviewUrl.value = URL.createObjectURL(file)
  try {
    const item = await uploadReferenceImage(file)
    const previewUrl = pendingPreviewUrl.value
    if (previewUrl) {
      const previousUrl = objectUrls.get(item.id)
      if (previousUrl && previousUrl !== previewUrl) URL.revokeObjectURL(previousUrl)
      objectUrls.set(item.id, previewUrl)
      pendingPreviewUrl.value = null
    }
    selected.value = item
    const nextHistory = [item, ...history.value.filter((entry) => entry.id !== item.id)]
    for (const evicted of nextHistory.slice(MAX_REFERENCE_HISTORY)) {
      releaseObjectUrl(evicted.id)
    }
    history.value = nextHistory.slice(0, MAX_REFERENCE_HISTORY)
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

function select(item: ReferenceImageItem) {
  selected.value = item
}

function clearSelected() {
  selected.value = null
}

async function remove(item: ReferenceImageItem) {
  if (deletingIds.has(item.id)) return
  deletingIds.add(item.id)
  try {
    await deleteReferenceImage(item.id)
    history.value = history.value.filter((entry) => entry.id !== item.id)
    if (selected.value?.id === item.id) {
      selected.value = null
    }
    releaseObjectUrl(item.id)
  } finally {
    deletingIds.delete(item.id)
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    history.value = await fetchReferenceImages()
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
    pendingPreviewUrl,
    pendingFilename,
    deletingIds,
    getObjectUrl,
    releaseObjectUrls,
    uploadAndSelect,
    select,
    clearSelected,
    remove,
    loadHistory,
  }
}
