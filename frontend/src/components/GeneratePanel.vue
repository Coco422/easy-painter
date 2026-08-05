<script setup lang="ts">
import { Check, ChevronDown, History, ImagePlus, Loader2, TriangleAlert, X } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import ReferenceHistoryDrawer from '@/components/ReferenceHistoryDrawer.vue'
import { useReferenceImages } from '@/composables/useReferenceImages'
import { resolveImageLayout } from '@/lib/image-layout'
import type { BatchCount, ImageSize, PublicModel } from '@/lib/types'

const props = defineProps<{
  prompt: string
  selectedModel: string
  selectedSize: ImageSize
  selectedBatchCount: BatchCount
  models: PublicModel[]
  maxLength: number
  submitting: boolean
  credits: number | null
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
  clearSelected,
} = useReferenceImages()

const promptLength = computed(() => props.prompt.length)
const promptOverLimit = computed(() => promptLength.value > props.maxLength)
const sizeOptions: Array<{ value: ImageSize; label: string; detail: string }> = [
  { value: 'auto', label: '自动', detail: '由渠道决定' },
  { value: '1024x1024', label: '方图', detail: '1024 × 1024' },
  { value: '1280x720', label: '横图', detail: '1280 × 720' },
  { value: '720x1280', label: '竖图', detail: '720 × 1280' },
  { value: '1792x1024', label: '横图', detail: '1792 × 1024' },
  { value: '1024x1792', label: '竖图', detail: '1024 × 1792' },
  { value: '1536x1024', label: '横图', detail: '1536 × 1024' },
  { value: '1024x1536', label: '竖图', detail: '1024 × 1536' },
  { value: '2048x2048', label: '2K 方图', detail: '2048 × 2048' },
  { value: '2048x1152', label: '2K 横图', detail: '2048 × 1152' },
  { value: '1152x2048', label: '2K 竖图', detail: '1152 × 2048' },
  { value: '3840x2160', label: '4K 横图', detail: '3840 × 2160' },
  { value: '2160x3840', label: '4K 竖图', detail: '2160 × 3840' },
]
const batchOptions: BatchCount[] = [1, 2, 4]

const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const drawerOpen = ref(false)
const sizePickerOpen = ref(false)
const sizePickerDialog = ref<HTMLElement | null>(null)
const referenceError = ref('')
const chipThumbUrl = computed(() => pendingPreviewUrl.value ?? (selected.value ? getObjectUrl(selected.value.id) : undefined))
const chipName = computed(() => (uploading.value ? pendingFilename.value : selected.value?.filename) ?? '')
const selectedSizeOption = computed(() => sizeOptions.find((option) => option.value === props.selectedSize) ?? sizeOptions[0])
const selectedSizeLayout = computed(() => resolveImageLayout(selectedSizeOption.value.value))
const selectedModelConfig = computed(() => props.models.find((model) => model.id === props.selectedModel))
const unitCost = computed(() => selectedModelConfig.value?.credit_cost ?? 0)
const estimatedCost = computed(() => unitCost.value * props.selectedBatchCount)
const estimatedBalance = computed(() => props.credits === null ? null : props.credits - estimatedCost.value)
const insufficientCredits = computed(() => estimatedBalance.value !== null && estimatedBalance.value < 0)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleSizePickerKeydown)
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

function openReferencePicker() {
  fileInput.value?.click()
}

function handleClearSelected() {
  referenceError.value = ''
  clearSelected()
}

function modelSupportsCurrentInput(model: PublicModel) {
  return model.enabled && (!selected.value || model.supports_reference_image !== false)
}

function sizeSupportedBySelectedModel(size: ImageSize) {
  const model = selectedModelConfig.value
  return !model?.supported_sizes.length || model.supported_sizes.includes(size)
}

function sizePreviewStyle(size: ImageSize) {
  const layout = resolveImageLayout(size)
  return {
    aspectRatio: layout.aspectRatio,
    '--image-ratio': layout.ratio,
  }
}

function handleSizePickerKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') sizePickerOpen.value = false
}

async function openSizePicker() {
  sizePickerOpen.value = true
  await nextTick()
  sizePickerDialog.value?.focus()
}

function chooseSize(size: ImageSize) {
  if (!sizeSupportedBySelectedModel(size)) return
  emit('update:size', size)
  sizePickerOpen.value = false
}

watch(sizePickerOpen, (open) => {
  if (open) window.addEventListener('keydown', handleSizePickerKeydown)
  else window.removeEventListener('keydown', handleSizePickerKeydown)
})
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
          <button v-else type="button" title="取消使用参考图" aria-label="取消使用参考图" @click="handleClearSelected">
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
            @click="openReferencePicker"
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

      <div class="field-label">
        <span>尺寸</span>
        <button
          type="button"
          class="size-picker-trigger"
          aria-haspopup="dialog"
          :aria-expanded="sizePickerOpen"
          @click="openSizePicker"
        >
          <span
            class="size-trigger-preview"
            :class="{ 'is-auto': selectedSizeOption.value === 'auto' }"
            :style="{ aspectRatio: selectedSizeLayout.aspectRatio }"
            aria-hidden="true"
          />
          <span class="size-trigger-copy">
            <strong>{{ selectedSizeOption.label }}</strong>
            <small>{{ selectedSizeOption.detail }}</small>
          </span>
          <ChevronDown :size="15" aria-hidden="true" />
        </button>
      </div>

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

      <button class="primary-button" :disabled="submitting || !selectedModel" @click="handleSubmit">
        {{ submitting ? '正在提交...' : '开始创作' }}
      </button>

      <div class="billing-estimate" :class="{ insufficient: insufficientCredits }" aria-live="polite">
        <div>
          <span>预计消耗</span>
          <strong>{{ unitCost }} 丝 × {{ selectedBatchCount }} 张 = {{ estimatedCost }} 丝</strong>
        </div>
        <div>
          <span>当前余额</span>
          <strong v-if="credits !== null">{{ credits }} 丝</strong>
          <strong v-else>登录后查看</strong>
        </div>
        <p v-if="insufficientCredits">预计还差 {{ Math.abs(estimatedBalance ?? 0) }} 丝；仍可提交，系统会按张独立处理，可能部分成功。</p>
        <p v-else-if="estimatedBalance !== null">提交后预计剩余 {{ estimatedBalance }} 丝；批量任务按张独立扣费与退款。</p>
        <p v-else>批量任务按张独立提交，允许部分成功。</p>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="sizePickerOpen" class="size-picker-backdrop" @click.self="sizePickerOpen = false">
        <section
          ref="sizePickerDialog"
          class="size-picker-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="size-picker-title"
          tabindex="-1"
        >
          <header class="size-picker-header">
            <div>
              <p class="section-label">Canvas size</p>
              <h2 id="size-picker-title">选择画布尺寸</h2>
              <span>方框展示成图的大致宽高比例。</span>
            </div>
            <button type="button" aria-label="关闭尺寸选择" @click="sizePickerOpen = false"><X :size="19" /></button>
          </header>

          <div class="size-picker-warning">
            <TriangleAlert :size="17" aria-hidden="true" />
            <span>当前接入的是低成本渠道，尺寸参数可能不会被严格执行，最终请以实际成图为准。</span>
          </div>

          <div class="size-picker-grid" role="listbox" aria-label="画布尺寸">
            <button
              v-for="option in sizeOptions"
              :key="option.value"
              type="button"
              class="size-option-card"
              :class="{ selected: selectedSize === option.value, 'is-auto': option.value === 'auto' }"
              :disabled="!sizeSupportedBySelectedModel(option.value)"
              role="option"
              :aria-selected="selectedSize === option.value"
              @click="chooseSize(option.value)"
            >
              <span class="size-option-visual" aria-hidden="true">
                <span class="size-option-shape" :style="sizePreviewStyle(option.value)">
                  <small v-if="option.value === 'auto'">AUTO</small>
                </span>
              </span>
              <span class="size-option-copy">
                <strong>{{ option.label }}</strong>
                <small>{{ option.detail }}</small>
                <em v-if="!sizeSupportedBySelectedModel(option.value)">当前模型不支持</em>
              </span>
              <Check v-if="selectedSize === option.value" :size="16" class="size-option-check" aria-hidden="true" />
            </button>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>
