<script setup lang="ts">
import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { Check, ChevronDown, History, ImagePlus, Loader2, PencilLine, Sparkles, TriangleAlert, X } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import ReferenceHistoryDrawer from '@/components/ReferenceHistoryDrawer.vue'
import { useReferenceImages } from '@/composables/useReferenceImages'
import { ApiError } from '@/lib/api'
import { resolveImageLayout } from '@/lib/image-layout'
import { modelBaseCreditCost, modelCreditCost } from '@/lib/model-pricing'
import { validGenerationCount } from '@/lib/generation-batch'
import { buildCreationPrompt, creationInputError, creationLanguages, creationStyles, creationTemplates, type CreationMode } from '@/lib/creation-presets'
import type { BatchCount, ImageSize, PublicModel, ReferenceImageItem } from '@/lib/types'

const props = defineProps<{
  prompt: string
  mode: CreationMode
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
  'update:mode': [value: CreationMode]
  'update:model': [value: string]
  'update:size': [value: ImageSize]
  'update:batch-count': [value: BatchCount]
  submit: [promptText: string]
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
  clearSelected,
} = useReferenceImages()

const promptLength = computed(() => props.prompt.length)
const promptOverLimit = computed(() => promptLength.value > props.maxLength)
const template = ref('free')
const style = ref('auto')
const language = ref('auto')
const submissionError = ref('')
const presetNotice = ref('')
const finalPrompt = computed(() => buildCreationPrompt(props.prompt, {
  mode: props.mode, template: template.value, style: style.value, language: language.value,
}))
const currentTemplate = computed(() => creationTemplates.find(item => item.id === template.value) ?? creationTemplates[0])
const currentModelLabel = computed(() => selectedModelConfig.value?.label ?? '暂无可用模型')
const modes: { id: CreationMode; label: string; icon: typeof Sparkles }[] = [
  { id: 'text', label: '灵感生图', icon: Sparkles },
  { id: 'reference', label: '参考生图', icon: ImagePlus },
  { id: 'edit', label: '修改图片', icon: PencilLine },
]

function applyTemplate(id: string) {
  const item = creationTemplates.find(entry => entry.id === id)
  if (!item) return
  template.value = id
  if (!props.prompt.trim()) {
    emit('update:prompt', item.example)
    presetNotice.value = `已填入${item.label}示例，可以继续修改。`
  } else {
    presetNotice.value = `已选择${item.label}，保留了你写的描述。`
  }
}
const promptInput = ref<HTMLTextAreaElement | null>(null)
const isUploading = computed(() => uploading.value || uploadingBatch.value)
function resetDraft() {
  if (props.submitting || isUploading.value) return false
  template.value = 'free'
  style.value = 'auto'
  language.value = 'auto'
  submissionError.value = ''
  presetNotice.value = ''
  referenceError.value = ''
  drawerOpen.value = false
  sizePickerOpen.value = false
  clearSelected()
  emit('update:prompt', '')
  emit('update:mode', 'text')
  return true
}
function focusPrompt() { promptInput.value?.focus({ preventScroll: true }) }
defineExpose({ applyTemplate, resetDraft, focusPrompt, isUploading })
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
const referencesOverLimit = computed(() => props.mode !== 'text' && selected.value.length > referenceLimit.value)
const selectedSizeOption = computed(() => sizeOptions.find((option) => option.value === props.selectedSize) ?? sizeOptions[0])
const selectedSizeLayout = computed(() => resolveImageLayout(selectedSizeOption.value.value))
const selectedModelConfig = computed(() => props.models.find((model) => model.id === props.selectedModel))
const unitCost = computed(() => modelCreditCost(selectedModelConfig.value, props.selectedSize))
const baseUnitCost = computed(() => modelBaseCreditCost(selectedModelConfig.value, props.selectedSize))
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
  if (!validGenerationCount(props.selectedBatchCount)) { submissionError.value = '生成数量需为正整数。'; return }
  submissionError.value = creationInputError(props.mode, props.prompt, finalPrompt.value, selected.value.length, props.maxLength)
  if (!submissionError.value) emit('submit', finalPrompt.value)
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
  return model.enabled && (props.mode === 'text' || model.supports_reference_image !== false)
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
watch([() => props.prompt, () => props.mode, template, style, language, selected], () => { submissionError.value = '' })
</script>

<template>
  <div class="generate-panel" id="create">
    <div class="creation-mode-picker" role="group" aria-label="创作模式">
      <button v-for="item in modes" :key="item.id" type="button" :aria-pressed="mode === item.id" :disabled="submitting || uploading || uploadingBatch" @click="emit('update:mode', item.id)">
        <component :is="item.icon" :size="17" aria-hidden="true" />{{ item.label }}
      </button>
    </div>
    <p class="creation-mode-hint">{{ mode === 'edit' ? '上传已有图片，描述想修改的内容。模型会重绘整张图。' : mode === 'reference' ? '上传草图或参考图片，结合描述生成新作品。' : '写下你的想法，或从右侧用途模板开始。' }}</p>
    <label v-if="mode !== 'edit'" class="field-label creation-template-field">
      <span>创作用途</span>
      <select v-model="template" class="model-select" :disabled="submitting" @change="presetNotice = ''">
        <option v-for="item in creationTemplates" :key="item.id" :value="item.id">{{ item.label }}</option>
      </select>
    </label>
    <div class="prompt-stack">
      <div class="panel-topline">
        <label for="creation-prompt" class="section-label">{{ mode === 'edit' ? '修改要求' : '描述你的想法' }}</label>
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
          ref="promptInput"
          id="creation-prompt"
          :value="prompt"
          :disabled="submitting"
          class="prompt-textarea"
          :placeholder="mode === 'edit' ? '例如：将标题改成英文，保留其他内容与布局' : '描述主体、布局和需要的文字，也可以粘贴或拖入参考图'"
          @input="emit('update:prompt', ($event.target as HTMLTextAreaElement).value)"
        />

        <div v-if="selected.length || uploading" class="reference-chips">
          <div v-for="(item, index) in selected" :key="item.id" class="reference-chip">
            <ProtectedImage :src="getObjectUrl(item.id) || item.thumbnail_url" :expires-at="item.media_expires_at" :alt="item.filename" />
            <span class="reference-chip-details">
              <span class="reference-chip-name">参考图 {{ index + 1 }} · {{ item.filename }}</span>
              <MediaExpiry class="selected-reference-expiry" state="available" :expires-at="item.media_expires_at" />
            </span>
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
        <p v-if="selected.length || mode !== 'text'" class="reference-count" :class="{ 'reference-error': referencesOverLimit }" aria-live="polite">
          {{ mode === 'text' && selected.length ? `已保留 ${selected.length} 张参考图，灵感生图不使用它们` : `已选 ${selected.length} / ${referenceLimit} 张参考图，按编号顺序提交` }}{{ referencesOverLimit ? '，请移除多余图片后提交' : '' }}
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
            <span>上传图片</span>
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
            <span>历史</span>
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
      <div v-if="mode !== 'edit'" class="creation-example-row">
        <button type="button" class="creation-text-button" :disabled="submitting" @click="emit('update:prompt', currentTemplate.example); presetNotice = '已填入示例描述，可以继续修改。'">填入示例描述</button>
        <span v-if="template !== 'free'">{{ currentTemplate.detail }}</span>
      </div>
      <p v-if="presetNotice && mode !== 'edit'" class="creation-notice" role="status">{{ presetNotice }}</p>
    </div>

    <ReferenceHistoryDrawer v-model:open="drawerOpen" :selection-limit="referenceLimit" :selection-disabled="uploadingBatch || submitting" @select="handleSelect" />

    <div class="creation-preset-fields">
      <label class="field-label"><span>视觉风格</span><select v-model="style" class="model-select" :disabled="submitting"><option v-for="item in creationStyles" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
      <label class="field-label"><span>图中文字</span><select v-model="language" class="model-select" :disabled="submitting"><option v-for="item in creationLanguages" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
    </div>

    <div class="panel-actions">
      <details class="creation-advanced">
        <summary>模型与提示词 <span>{{ currentModelLabel }}</span></summary>
      <label class="field-label">
        <span>模型</span>
        <select
          :value="selectedModel"
          class="model-select"
          :disabled="submitting || uploading || uploadingBatch"
          @change="emit('update:model', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="model in models.filter((item) => item.enabled)" :key="model.id" :value="model.id" :disabled="!modelSupportsCurrentInput(model)">
            {{ model.label }}{{ mode !== 'text' && model.supports_reference_image === false ? '（不支持参考图）' : '' }}（{{ modelCreditCost(model, selectedSize) }} 丝/张{{ modelBaseCreditCost(model, selectedSize) !== modelCreditCost(model, selectedSize) ? `，原价 ${modelBaseCreditCost(model, selectedSize)} 丝` : '' }}）
          </option>
        </select>
      </label>
      <p class="creation-notice">预设会补充到描述之后，实际效果取决于所选模型。</p>
      <div class="creation-final-prompt"><span>最终提示词 · {{ finalPrompt.length }} / {{ maxLength }} 字</span><p>{{ finalPrompt || '填写描述后，可以在这里检查包含预设的完整提示词。' }}</p></div>
      </details>

      <div class="field-label">
        <span>尺寸</span>
        <button
          type="button"
          class="size-picker-trigger"
          aria-haspopup="dialog"
          :aria-expanded="sizePickerOpen"
          :disabled="submitting"
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
            :disabled="submitting"
            @click="emit('update:batch-count', count)"
          >
            {{ count }} 张
          </button>
        </span>
        <input class="model-select batch-custom-count" type="number" min="1" step="1" aria-label="自定义生成数量" :value="selectedBatchCount" :disabled="submitting" @input="emit('update:batch-count', Number(($event.target as HTMLInputElement).value))" />
      </label>

      <p v-if="submissionError" class="creation-submit-error" role="alert">{{ submissionError }}</p>
      <button class="primary-button" :disabled="submitting || uploading || uploadingBatch || referencesOverLimit || !selectedModel || !validGenerationCount(selectedBatchCount)" @click="handleSubmit">
        <Sparkles :size="17" aria-hidden="true" />{{ submitting ? '正在提交...' : mode === 'edit' ? '生成修改版' : '开始创作' }}
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

<style scoped>
.generate-panel { display: grid; gap: 20px; padding: 22px; border-radius: 12px; box-shadow: none; }
.creation-mode-picker { display: flex; gap: 4px; }
.creation-mode-picker button { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 12px 4px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; color: var(--text-secondary); font: inherit; font-size: 12px; cursor: pointer; transition: background 160ms, border-color 160ms; }
.creation-mode-picker button[aria-pressed='true'] { color: var(--accent-strong); background: var(--accent-soft); border-color: var(--border-accent); }
.creation-mode-picker button:disabled { cursor: wait; opacity: .6; }
.creation-mode-hint { margin: -8px 0 0; font-size: 12px; line-height: 1.6; color: var(--text-secondary); }
.creation-template-field, .creation-preset-fields .field-label { min-width: 0; }
.generate-panel .section-label { font-size: 13px; letter-spacing: 0; text-transform: none; color: var(--text-primary); font-weight: 500; }
.generate-panel .char-count { white-space: nowrap; font-size: 11px; }
.generate-panel .prompt-textarea { min-height: 168px; font-size: 14px; line-height: 1.7; padding: 12px; }
.generate-panel .reference-chips { padding: 0 10px; }
.generate-panel .reference-count { margin: 0 12px 8px; }
.generate-panel .prompt-toolbar { justify-content: flex-start; gap: 8px; padding: 8px; }
.generate-panel .prompt-tool-button { display: inline-flex; align-items: center; justify-content: center; width: auto; height: auto; min-height: 36px; gap: 6px; padding: 8px; font-size: 12px; }
.creation-example-row { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 12px; color: var(--text-secondary); }
.creation-text-button { padding: 0; border: 0; background: transparent; color: var(--accent-strong); font: inherit; cursor: pointer; text-align: left; }
.creation-text-button:disabled { opacity: .6; cursor: wait; }
.creation-notice { margin: 0; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.creation-preset-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.generate-panel .model-select { padding: 10px 30px 10px 10px; font-size: 13px; border-radius: 6px; }
.generate-panel .panel-actions { grid-template-columns: minmax(0, 1fr); align-items: stretch; gap: 16px; margin: 0; }
.generate-panel .field-label { gap: 8px; font-size: 13px; }
.creation-advanced { grid-row: 3; min-width: 0; }
.creation-advanced summary { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.creation-advanced summary::before { content: '+'; }
.creation-advanced[open] summary::before { content: '−'; }
.creation-advanced summary span { flex: 1; text-align: right; color: var(--text-primary); overflow-wrap: anywhere; }
.creation-advanced .field-label { margin: 12px 0; }
.creation-final-prompt { margin-top: 12px; color: var(--text-secondary); font-size: 12px; }
.creation-final-prompt p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; margin: 8px 0 0; }
.generate-panel .size-picker-trigger { border-radius: 6px; }
.generate-panel .size-trigger-copy { min-width: 0; }
.generate-panel .primary-button { display: flex; justify-content: center; align-items: center; gap: 8px; width: 100%; border-radius: 6px; }
.generate-panel .billing-estimate { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; background: transparent; border: 0; border-top: 1px solid var(--border); border-radius: 0; padding: 16px 0 0; }
.generate-panel .billing-estimate > div { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.generate-panel .billing-estimate span { font-size: 12px; letter-spacing: 0; }
.generate-panel .billing-estimate strong { font-size: 12px; overflow-wrap: anywhere; }
.generate-panel .billing-estimate p { justify-self: stretch; text-align: left; line-height: 1.6; }
.creation-submit-error { margin: 0; color: var(--error); font-size: 13px; line-height: 1.6; }
.generate-panel button:focus-visible, .creation-advanced summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
@media (max-width: 900px) { .generate-panel { padding: 20px; } }
@media (pointer: coarse) { .generate-panel .prompt-textarea, .generate-panel .model-select { font-size: 16px; } .generate-panel .creation-text-button, .generate-panel .prompt-tool-button { min-height: 44px; } }
.reference-chip :deep(.protected-image) { width: 38px; height: 38px; min-height: 0; flex: 0 0 38px; border-radius: var(--radius-sm); }
.reference-chip :deep(.image-placeholder) { min-height: 0; padding: 2px; font-size: 9px; }
.reference-chip-details { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.selected-reference-expiry { font-size: 10px; white-space: normal; }
</style>
