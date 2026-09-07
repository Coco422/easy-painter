<script setup lang="ts">
import { Check, ChevronDown, History, ImagePlus, Loader2, TriangleAlert, X } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import ReferenceHistoryDrawer from '@/components/ReferenceHistoryDrawer.vue'
import { useReferenceImages } from '@/composables/useReferenceImages'
import { ApiError } from '@/lib/api'
import { resolveImageLayout } from '@/lib/image-layout'
import type { BatchCount, ImageSize, PublicModel, ReferenceImageItem } from '@/lib/types'

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
  deselect,
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
const uploadingBatch = ref(false)
const referenceLimit = computed(() => selectedModelConfig.value?.supports_reference_image === false ? 0 : (selectedModelConfig.value?.max_reference_images ?? 5))
const referencesOverLimit = computed(() => selected.value.length > referenceLimit.value)
const selectedSizeOption = computed(() => sizeOptions.find((option) => option.value === props.selectedSize) ?? sizeOptions[0])
const selectedSizeLayout = computed(() => resolveImageLayout(selectedSizeOption.value.value))
const selectedModelConfig = computed(() => props.models.find((model) => model.id === props.selectedModel))
const unitCost = computed(() => selectedModelConfig.value?.credit_cost ?? 0)
const baseUnitCost = computed(() => selectedModelConfig.value?.base_credit_cost ?? unitCost.value)
const hasDiscount = computed(() => baseUnitCost.value !== unitCost.value)
const estimatedCost = computed(() => unitCost.value * props.selectedBatchCount)
const estimatedBalance = computed(() => props.credits === null ? null : props.credits - estimatedCost.value)
const insufficientCredits = computed(() => estimatedBalance.value !== null && estimatedBalance.value < 0)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleSizePickerKeydown)
  releaseObjectUrls()
})

function handleSubmit() {
  if (uploading.value || uploadingBatch.value || referencesOverLimit.value || props.submitting) return
  emit('submit')
}

async function handleUpload(file: File) {
  if (uploading.value) {
    referenceError.value = '已有参考图正在上传，请稍候。'
    return
  }
  referenceError.value = ''
  try {
    await uploadAndSelect(file, false, referenceLimit.value)
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.detail?.max_reference_images) {
      const limit = error.detail.max_reference_images as number
      const current = error.detail.current_count as number | undefined
      const evict = error.detail.evict_count as number | undefined
      const summary = current === undefined ? `参考图已达到 ${limit} 张上限。` : `当前已有 ${current}/${limit} 张参考图。`
      if (window.confirm(`${summary}\n继续将自动淘汰最早上传的 ${evict ?? 1} 张参考图，此操作不可恢复。`)) {
        try {
          await uploadAndSelect(file, true, referenceLimit.value)
          return
        } catch (retryError) {
          referenceError.value = retryError instanceof Error ? retryError.message : '参考图上传失败，请稍后重试。'
          return
        }
      }
      referenceError.value = '已取消上传；你可以先在参考图历史中手动整理。'
      return
    }
    referenceError.value = error instanceof Error ? error.message : '参考图上传失败，请稍后重试。'
  }
}

async function handleFiles(files: File[]) {
  if (!files.length) return
  if (uploadingBatch.value || uploading.value || props.submitting) return
  if (selected.value.length + files.length > referenceLimit.value) {
    referenceError.value = `当前模型单次最多支持 ${referenceLimit.value} 张参考图，已选 ${selected.value.length} 张。`
    return
  }
  uploadingBatch.value = true
  try {
    for (const file of files) {
      await handleUpload(file)
      if (referenceError.value) break
    }
  } finally {
    uploadingBatch.value = false
  }
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.items ?? [])
    .filter((item) => item.type.startsWith('image/'))
    .map((item) => item.getAsFile()).filter((file): file is File => file !== null)
  if (files.length) {
    event.preventDefault()
    void handleFiles(files)
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
  void handleFiles(Array.from(event.dataTransfer?.files ?? []).filter((entry) => entry.type.startsWith('image/')))
}

function handleReferenceFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  void handleFiles(files)
}

function openReferencePicker() {
  fileInput.value?.click()
}

function handleSelect(item: ReferenceImageItem) {
  referenceError.value = ''
  try { select(item, referenceLimit.value) }
  catch (error) { referenceError.value = error instanceof Error ? error.message : '选择失败。' }
}

function modelSupportsCurrentInput(model: PublicModel) {
  return model.enabled && (selected.value.length === 0 || model.supports_reference_image !== false)
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

        <div v-if="selected.length || uploading" class="reference-chips">
          <div v-for="(item, index) in selected" :key="item.id" class="reference-chip">
            <img v-if="getObjectUrl(item.id)" :src="getObjectUrl(item.id)" :alt="item.filename" />
            <span v-else class="reference-chip-placeholder" aria-hidden="true"><ImagePlus :size="18" /></span>
            <span class="reference-chip-name">参考图 {{ index + 1 }} · {{ item.filename }}</span>
            <button type="button" :aria-label="`取消使用参考图 ${index + 1}`" :disabled="submitting || uploadingBatch" @click="deselect(item.id)">
              <X :size="14" />
            </button>
          </div>
          <div v-if="uploading" class="reference-chip uploading">
            <img v-if="pendingPreviewUrl" :src="pendingPreviewUrl" :alt="pendingFilename" />
            <span class="reference-chip-name">{{ pendingFilename }}</span>
            <Loader2 :size="16" class="reference-chip-spinner" />
          </div>
        </div>
        <p class="reference-count" :class="{ 'reference-error': referencesOverLimit }" aria-live="polite">
          已选 {{ selected.length }} / {{ referenceLimit }} 张参考图{{ referencesOverLimit ? '，请移除多余图片后提交' : '，按编号顺序提交' }}
        </p>
        <p v-if="referenceError" class="reference-error">{{ referenceError }}</p>

        <div class="prompt-toolbar">
          <button
            type="button"
            class="prompt-tool-button"
            title="上传参考图"
            aria-label="上传参考图"
            :disabled="uploading || uploadingBatch || submitting || selected.length >= referenceLimit"
            @click="openReferencePicker"
          >
            <ImagePlus :size="18" />
          </button>
          <button
            type="button"
            class="prompt-tool-button"
            title="参考图历史"
            aria-label="参考图历史"
            :disabled="uploading || uploadingBatch || submitting"
            @click="drawerOpen = true"
          >
            <History :size="18" />
          </button>
          <input
            ref="fileInput"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            hidden
            @change="handleReferenceFileChange"
          />
        </div>
      </div>
    </div>

    <ReferenceHistoryDrawer v-model:open="drawerOpen" :selection-limit="referenceLimit" :selection-disabled="uploadingBatch || submitting" @select="handleSelect" />

    <div class="panel-actions">
      <label class="field-label">
        <span>模型</span>
        <select
          :value="selectedModel"
          class="model-select"
          @change="emit('update:model', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="model in models" :key="model.id" :value="model.id" :disabled="!modelSupportsCurrentInput(model)">
            {{ model.label }}{{ selected.length > 0 && model.supports_reference_image === false ? '（不支持参考图）' : '' }}（{{ model.credit_cost }} 丝/张{{ model.base_credit_cost !== model.credit_cost ? `，原价 ${model.base_credit_cost} 丝` : '' }}）
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

      <button class="primary-button" :disabled="submitting || uploading || uploadingBatch || referencesOverLimit || !selectedModel" @click="handleSubmit">
        {{ submitting ? '正在提交...' : '开始创作' }}
      </button>

      <div class="billing-estimate" :class="{ insufficient: insufficientCredits }" aria-live="polite">
        <div>
          <span>预计消耗</span>
          <strong>{{ unitCost }} 丝 × {{ selectedBatchCount }} 张 = {{ estimatedCost }} 丝<span v-if="hasDiscount">（原价 {{ baseUnitCost * selectedBatchCount }} 丝）</span></strong>
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
