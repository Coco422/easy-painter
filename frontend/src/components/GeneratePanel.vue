<script setup lang="ts">
import { History, ImagePlus, Loader2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref } from 'vue'

import ReferenceHistoryDrawer from '@/components/ReferenceHistoryDrawer.vue'
import { useReferenceImages } from '@/composables/useReferenceImages'
import type { BatchCount, ImageSize, PublicModel } from '@/lib/types'

const props = defineProps<{
  prompt: string
  selectedModel: string
  selectedSize: ImageSize
  selectedBatchCount: BatchCount
  models: PublicModel[]
  maxLength: number
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:prompt': [value: string]
  'update:model': [value: string]
  'update:size': [value: ImageSize]
  'update:batch-count': [value: BatchCount]
  submit: []
}>()

const {
  selected,
  uploading,
  pendingPreviewUrl,
  pendingFilename,
  getObjectUrl,
  releaseObjectUrls,
  uploadAndSelect,
  select,
  remove,
} = useReferenceImages()

const promptLength = computed(() => props.prompt.length)
const promptOverLimit = computed(() => promptLength.value > props.maxLength)
const sizeOptions: Array<{ value: ImageSize; label: string }> = [
  { value: 'auto', label: '自动' },
  { value: '1024x1024', label: '1024 x 1024 方图' },
  { value: '1280x720', label: '1280 x 720 横图' },
  { value: '720x1280', label: '720 x 1280 竖图' },
  { value: '1792x1024', label: '1792 x 1024 横图' },
  { value: '1024x1792', label: '1024 x 1792 竖图' },
  { value: '1536x1024', label: '1536 x 1024 横图' },
  { value: '1024x1536', label: '1024 x 1536 竖图' },
  { value: '2048x2048', label: '2048 x 2048 2K 方图' },
  { value: '2048x1152', label: '2048 x 1152 2K 横图' },
  { value: '1152x2048', label: '1152 x 2048 2K 竖图' },
  { value: '3840x2160', label: '3840 x 2160 4K 横图' },
  { value: '2160x3840', label: '2160 x 3840 4K 竖图' },
]
const batchOptions: BatchCount[] = [1, 2, 4]

const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const drawerOpen = ref(false)
const referenceError = ref('')
const chipThumbUrl = computed(() => pendingPreviewUrl.value ?? (selected.value ? getObjectUrl(selected.value.id) : undefined))
const chipName = computed(() => (uploading.value ? pendingFilename.value : selected.value?.filename) ?? '')

onBeforeUnmount(() => {
  releaseObjectUrls()
})

function handleSubmit() {
  emit('submit')
}

async function handleUpload(file: File) {
  if (uploading.value) {
    referenceError.value = '已有参考图正在上传，请稍候。'
    return
  }
  referenceError.value = ''
  try {
    await uploadAndSelect(file)
  } catch (error) {
    referenceError.value = error instanceof Error ? error.message : '参考图上传失败，请稍后重试。'
  }
}

function handlePaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (!item.type.startsWith('image/')) continue
    const file = item.getAsFile()
    if (file) {
      event.preventDefault()
      void handleUpload(file)
      return
    }
  }
}

function handleDragOver() {
  isDragging.value = true
}

function handleDragLeave(event: DragEvent) {
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) {
    isDragging.value = false
  }
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  const file = Array.from(event.dataTransfer?.files ?? []).find((entry) => entry.type.startsWith('image/'))
  if (file) {
    void handleUpload(file)
  }
}

function handleReferenceFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) {
    void handleUpload(file)
  }
}

async function handleRemoveSelected() {
  const item = selected.value
  if (!item) return
  referenceError.value = ''
  try {
    await remove(item)
  } catch (error) {
    referenceError.value = error instanceof Error ? error.message : '删除参考图失败，请稍后重试。'
  }
}

function modelSupportsCurrentInput(model: PublicModel) {
  return model.enabled && (!selected.value || model.supports_reference_image !== false)
}

function selectedModelConfig() {
  return props.models.find((model) => model.id === props.selectedModel)
}

function sizeSupportedBySelectedModel(size: ImageSize) {
  const model = selectedModelConfig()
  return !model?.supported_sizes.length || model.supported_sizes.includes(size)
}
</script>

<template>
  <div class="generate-panel" id="create">
    <div class="prompt-stack">
      <div class="panel-topline">
        <span class="section-label">创作提示</span>
        <p class="char-count" :class="{ over: promptOverLimit }">{{ promptLength }} / {{ maxLength }}</p>
      </div>
      <div
        class="prompt-input-shell"
        :class="{ dragging: isDragging }"
        @paste="handlePaste"
        @dragover.prevent="handleDragOver"
        @dragleave="handleDragLeave"
        @drop.prevent="handleDrop"
      >
        <textarea
          :value="prompt"
          class="prompt-textarea"
          placeholder="请输入画面描述，也可以直接粘贴或拖入参考图"
          @input="emit('update:prompt', ($event.target as HTMLTextAreaElement).value)"
        />

        <div v-if="selected || uploading" class="reference-chip" :class="{ uploading }">
          <img v-if="chipThumbUrl" :src="chipThumbUrl" :alt="chipName" />
          <span v-else class="reference-chip-placeholder" aria-hidden="true"><ImagePlus :size="18" /></span>
          <span class="reference-chip-name">{{ chipName }}</span>
          <Loader2 v-if="uploading" :size="16" class="reference-chip-spinner" />
          <button v-else type="button" title="移除参考图" aria-label="移除参考图" @click="handleRemoveSelected">
            <X :size="14" />
          </button>
        </div>
        <p v-if="referenceError" class="reference-error">{{ referenceError }}</p>

        <div class="prompt-toolbar">
          <button
            type="button"
            class="prompt-tool-button"
            title="上传参考图"
            aria-label="上传参考图"
            :disabled="uploading"
            @click="fileInput?.click()"
          >
            <ImagePlus :size="18" />
          </button>
          <button
            type="button"
            class="prompt-tool-button"
            title="参考图历史"
            aria-label="参考图历史"
            @click="drawerOpen = true"
          >
            <History :size="18" />
          </button>
          <input
            ref="fileInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            @change="handleReferenceFileChange"
          />
        </div>
      </div>
    </div>

    <ReferenceHistoryDrawer v-model:open="drawerOpen" @select="select" />

    <div class="panel-actions">
      <label class="field-label">
        <span>模型</span>
        <select
          :value="selectedModel"
          class="model-select"
          @change="emit('update:model', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="model in models" :key="model.id" :value="model.id" :disabled="!modelSupportsCurrentInput(model)">
            {{ model.label }}{{ selected && model.supports_reference_image === false ? '（不支持参考图）' : '' }}（{{ model.credit_cost }} 丝/张）
          </option>
        </select>
      </label>

      <label class="field-label">
        <span>尺寸</span>
        <select
          :value="selectedSize"
          class="model-select"
          @change="emit('update:size', ($event.target as HTMLSelectElement).value as ImageSize)"
        >
          <option
            v-for="option in sizeOptions"
            :key="option.value"
            :value="option.value"
            :disabled="!sizeSupportedBySelectedModel(option.value)"
          >
            {{ option.label }}{{ !sizeSupportedBySelectedModel(option.value) ? '（当前模型不支持）' : '' }}
          </option>
        </select>
      </label>

      <label class="field-label">
        <span>数量</span>
        <span class="batch-segmented" role="group" aria-label="生成数量">
          <button
            v-for="count in batchOptions"
            :key="count"
            type="button"
            :class="{ active: selectedBatchCount === count }"
            :aria-pressed="selectedBatchCount === count"
            @click="emit('update:batch-count', count)"
          >
            {{ count }} 张
          </button>
        </span>
      </label>

      <button class="primary-button" :disabled="submitting" @click="handleSubmit">
        {{ submitting ? '正在提交...' : '开始创作' }}
      </button>
    </div>
  </div>
</template>
