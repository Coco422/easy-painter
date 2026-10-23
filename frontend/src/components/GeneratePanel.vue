<script setup lang="ts">
import ProtectedImage from '@/components/ProtectedImage.vue'
import MediaExpiry from '@/components/MediaExpiry.vue'
import { Check, ChevronDown, History, ImagePlus, Loader2, Sparkles, X } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NSelect } from 'naive-ui'

import ReferenceHistoryDrawer from '@/components/ReferenceHistoryDrawer.vue'
import { useReferenceImages } from '@/composables/useReferenceImages'
import { ApiError } from '@/lib/api'
import { resolveImageLayout } from '@/lib/image-layout'
import { modelBaseCreditCost, modelCreditCost } from '@/lib/model-pricing'
import { validGenerationCount } from '@/lib/generation-batch'
import { GENERATION_SIZE_OPTIONS } from '@/lib/generation-sizes'
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
const editMode = computed(() => props.mode === 'edit')
const templateOptions = computed(() => creationTemplates.map(item => ({ label: item.label, value: item.id })))
const styleOptions = computed(() => creationStyles.map(item => ({ label: item.label, value: item.id })))
const languageOptions = computed(() => creationLanguages.map(item => ({ label: item.label, value: item.id })))
const modelOptions = computed(() => props.models.filter(item => item.enabled).map(model => ({
  label: `${model.label} · ${modelCreditCost(model, props.selectedSize)} 丝${props.mode !== 'text' && model.supports_reference_image === false ? '（不支持参考图）' : ''}`,
  value: model.id,
  disabled: !modelSupportsCurrentInput(model),
})))
const activePresets = computed(() => editMode.value ? [] : [
  { id: 'template', label: currentTemplate.value.label, active: template.value !== 'free' },
  { id: 'style', label: creationStyles.find(item => item.id === style.value)?.label ?? '', active: style.value !== 'auto' },
  { id: 'language', label: creationLanguages.find(item => item.id === language.value)?.label ?? '', active: language.value !== 'auto' },
].filter(item => item.active))

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
const sizeOptions = GENERATION_SIZE_OPTIONS
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

function updateTemplate(value: string | number | null) {
  if (typeof value !== 'string') return
  template.value = value
  presetNotice.value = ''
}

function updateStyle(value: string | number | null) {
  if (typeof value === 'string') style.value = value
}

function updateLanguage(value: string | number | null) {
  if (typeof value === 'string') language.value = value
}

function updateModel(value: string | number | null) {
  if (typeof value === 'string') emit('update:model', value)
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

function removePreset(id: string) {
  if (id === 'template') template.value = 'free'
  if (id === 'style') style.value = 'auto'
  if (id === 'language') language.value = 'auto'
}
</script>

<template>
  <div class="generate-panel" id="create">
    <div
      class="prompt-card"
      :class="{ dragging: isDragging, 'is-submitting': submitting }"
      @paste="handlePaste"
      @dragover.prevent="handleDragOver"
      @dragleave="handleDragLeave"
      @drop.prevent="handleDrop"
    >
      <label for="creation-prompt" class="sr-only">{{ editMode ? '修改要求' : '描述你的想法' }}</label>
      <textarea
        ref="promptInput"
        id="creation-prompt"
        :value="prompt"
        :disabled="submitting"
        class="prompt-textarea"
        :placeholder="editMode ? '例如：将标题改成英文，保留其他内容与布局' : '描述你想看到的画面。像和画师聊天一样写，也可以粘贴或拖入参考图。'"
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
        {{ mode === 'text' && selected.length ? `已保留 ${selected.length} 张参考图，本次不会使用` : `${selected.length} / ${referenceLimit} 张参考图，按编号顺序提交` }}{{ referencesOverLimit ? '，请移除多余图片后提交' : '' }}
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
          <ImagePlus :size="16" />
          <span>参考图</span>
        </button>
        <button
          type="button"
          class="prompt-tool-button"
          title="参考图历史"
          aria-label="参考图历史"
          :disabled="uploading || uploadingBatch || submitting"
          @click="drawerOpen = true"
        >
          <History :size="16" />
          <span>历史</span>
        </button>
        <span class="char-count" :class="{ over: promptOverLimit }">{{ promptLength }} / {{ maxLength }}</span>
      </div>
      <input
        ref="fileInput"
        type="file"
        multiple
        accept="image/png,image/jpeg,image/webp"
        hidden
        @change="handleReferenceFileChange"
      />
    </div>

    <ReferenceHistoryDrawer v-model:open="drawerOpen" :selection-limit="referenceLimit" :selection-disabled="uploadingBatch || submitting" @select="handleSelect" />

    <p v-if="presetNotice && !editMode" class="creation-notice" role="status">{{ presetNotice }}</p>

    <div class="parameter-pills" role="group" aria-label="生成参数">
      <div v-if="!editMode" class="pill pill--select">
        <span class="pill-label">创作用途</span>
        <NSelect class="parameter-select" aria-label="创作用途" :value="template" :options="templateOptions" :disabled="submitting" size="small" @update:value="updateTemplate" />
      </div>
      <div v-if="!editMode" class="pill pill--select">
        <span class="pill-label">视觉风格</span>
        <NSelect class="parameter-select" aria-label="视觉风格" :value="style" :options="styleOptions" :disabled="submitting" size="small" @update:value="updateStyle" />
      </div>
      <div v-if="!editMode" class="pill pill--select">
        <span class="pill-label">图中文字</span>
        <NSelect class="parameter-select" aria-label="图中文字" :value="language" :options="languageOptions" :disabled="submitting" size="small" @update:value="updateLanguage" />
      </div>
      <div class="pill pill--action">
        <span class="pill-label">尺寸</span>
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
            :style="{ aspectRatio: selectedSizeLayout.aspectRatio, '--image-ratio': selectedSizeLayout.ratio }"
            aria-hidden="true"
          />
          <span class="size-trigger-copy">{{ selectedSizeOption.label }} <small>{{ selectedSizeOption.detail }}</small></span>
          <ChevronDown :size="13" aria-hidden="true" />
        </button>
      </div>
      <div class="pill pill--action pill--quantity">
        <span class="pill-label">数量</span>
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
        <input class="batch-custom-count" type="number" min="1" step="1" aria-label="自定义生成数量" :value="selectedBatchCount" :disabled="submitting" @input="emit('update:batch-count', Number(($event.target as HTMLInputElement).value))" />
      </div>
      <div class="pill pill--select pill--model">
        <span class="pill-label">模型</span>
        <NSelect class="parameter-select" aria-label="模型" :value="selectedModel" :options="modelOptions" :disabled="submitting || uploading || uploadingBatch" size="small" @update:value="updateModel" />
      </div>
      <button
        v-for="preset in activePresets"
        :key="preset.id"
        type="button"
        class="pill pill--removable"
        :aria-label="`移除预设 ${preset.label}`"
        :disabled="submitting"
        @click="removePreset(preset.id)"
      >
        <span>{{ preset.label }}</span><X :size="12" aria-hidden="true" />
      </button>
    </div>

    <p v-if="submissionError" class="creation-submit-error" role="alert">{{ submissionError }}</p>

    <div class="submit-row">
      <button class="primary-button" :disabled="submitting || uploading || uploadingBatch || referencesOverLimit || !selectedModel || !validGenerationCount(selectedBatchCount)" @click="handleSubmit">
        <Sparkles :size="16" aria-hidden="true" />{{ submitting ? '正在提交…' : editMode ? '生成修改版' : '开始创作' }}
      </button>
      <div class="billing-estimate" :class="{ insufficient: insufficientCredits }" aria-live="polite">
        <strong>{{ unitCost }} 丝 × {{ selectedBatchCount }} 张 = {{ estimatedCost }} 丝</strong>
        <span v-if="insufficientCredits">余额 {{ credits }} 丝，还差 {{ Math.abs(estimatedBalance ?? 0) }} 丝</span>
        <span v-else-if="credits !== null">余额 {{ credits }} 丝</span>
        <span v-else>登录后查看余额</span>
      </div>
    </div>
    <p class="foot-note">
      <template v-if="hasDiscount">原价 {{ baseUnitCost * selectedBatchCount }} 丝 · </template>按张独立扣费，失败全额退回。
    </p>

    <details class="creation-advanced">
      <summary>{{ currentModelLabel }} · 最终提示词 <span>{{ finalPrompt.length }} / {{ maxLength }}</span></summary>
      <div class="creation-final-prompt">{{ finalPrompt || '填写描述后，可以在这里检查包含预设的完整提示词。' }}</div>
    </details>

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
              <h2 id="size-picker-title">选择图片尺寸</h2>
              <span>方框展示成图的大致宽高比例。</span>
            </div>
            <button type="button" aria-label="关闭尺寸选择" @click="sizePickerOpen = false"><X :size="19" /></button>
          </header>

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
          <p class="size-picker-note">遵循 OpenAI 官方尺寸上限。4K 高于 2560 × 1440，属于实验性尺寸，仅在渠道明确支持时开放；自动按 1K 计费。</p>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.generate-panel { display: grid; min-width: 0; gap: 16px; padding: 16px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.prompt-card { border: 1px solid var(--border); border-radius: 14px; background: var(--bg-input); transition: border-color 160ms, box-shadow 160ms; }
.prompt-card:focus-within { border-color: var(--border-accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.prompt-card.dragging { border-color: var(--accent); background: var(--accent-glow); }
.prompt-card.is-submitting { opacity: .72; }
.prompt-textarea {
  display: block; width: 100%; min-height: 156px; padding: 14px 14px 4px;
  border: 0; background: transparent; color: var(--text-primary); resize: none; outline: none;
  font: 14px/1.75 var(--font-body);
}
.prompt-textarea::placeholder { color: var(--text-muted); }
.prompt-toolbar { display: flex; align-items: center; gap: 4px; padding: 4px 8px 8px 10px; }
.prompt-tool-button {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  width: auto; height: auto; min-height: 30px; padding: 4px 9px; border: 0; border-radius: 7px;
  background: transparent; color: var(--text-secondary); font: inherit; font-size: 12.5px; white-space: nowrap; cursor: pointer;
  flex: none;
}
.prompt-tool-button span { white-space: nowrap; }
.prompt-tool-button svg { flex: none; }
.char-count { margin-left: auto; padding-right: 2px; font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.prompt-tool-button:hover:not(:disabled) { background: var(--bg-hover); color: var(--accent-strong); }
.prompt-tool-button:disabled { opacity: .5; cursor: not-allowed; }
.char-count.over { color: var(--error); }

.reference-chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 10px 4px; }
.reference-chip { display: flex; align-items: center; gap: 8px; max-width: 100%; padding: 4px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-surface); }
.reference-chip > button { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; padding: 2px; }
.reference-chip :deep(.protected-image) { width: 34px; height: 34px; min-height: 0; flex: 0 0 34px; border-radius: 5px; }
.reference-chip :deep(.image-placeholder) { min-height: 0; padding: 2px; font-size: 9px; }
.reference-chip-details { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.reference-chip-name { font-size: 11.5px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-reference-expiry { font-size: 10px; white-space: normal; }
.reference-count { margin: 0 12px 6px; font-size: 11.5px; color: var(--text-muted); }
.reference-error { margin: 0 12px 8px; color: var(--error); font-size: 12px; line-height: 1.6; }

.parameter-pills { display: grid; min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.pill {
  position: relative; display: flex; align-items: center; gap: 5px; width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box;
  min-height: 34px; padding: 0 10px;
  border: 1px solid var(--border); border-radius: 999px;
  background: transparent; color: var(--text-primary); font: inherit; font-size: 12.5px;
}
.pill:hover { border-color: var(--border-accent); background: var(--accent-glow); }
.pill-label { flex: 0 0 auto; color: var(--text-muted); font-size: 11.5px; white-space: nowrap; }
.parameter-select { flex: 1 1 0; min-width: 0; }
.parameter-select :deep(.n-base-selection) { min-width: 0; width: 100%; height: 28px; border: 0; background: transparent; box-shadow: none; }
.parameter-select :deep(.n-base-selection-label) { min-width: 0; padding: 0 2px; background: transparent; }
.parameter-select :deep(.n-base-selection-input) { min-width: 0; color: var(--text-primary); font: inherit; font-size: 12px; }
.parameter-select :deep(.n-base-selection-input__content) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.parameter-select :deep(.n-base-selection__border), .parameter-select :deep(.n-base-selection__state-border) { display: none; }
.parameter-select :deep(.n-base-selection .n-base-suffix) { width: 18px; }
.parameter-select :deep(.n-base-selection .n-base-suffix__arrow) { font-size: 11px; color: var(--text-muted); }
.parameter-select :deep(.n-base-selection--disabled) { opacity: .6; }
.pill--select { display: grid; gap: 4px; padding: 8px 12px; border-radius: 10px; }
.pill > svg { color: var(--text-muted); flex: none; }
.pill--action { min-width: 0; padding-right: 6px; }
.pill--model, .pill--quantity { grid-column: 1 / -1; }
.pill--removable { justify-self: start; width: fit-content; max-width: 100%; }
.pill--removable { color: var(--accent-strong); border-color: var(--border-accent); background: var(--accent-soft); cursor: pointer; }
.pill--removable svg { opacity: .7; }

.size-picker-trigger {
  display: inline-flex; flex: 1 1 auto; align-items: center; gap: 4px; width: auto; min-width: 0; min-height: 0; height: auto;
  padding: 0; border: 0; border-radius: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer;
}
.size-trigger-preview { width: 12px; height: min(20px, calc(12px / var(--image-ratio, 1))); border: 1.5px solid var(--text-muted); border-radius: 2px; flex: 0 0 auto; }
.size-trigger-preview.is-auto { border-style: dashed; }
.size-trigger-copy { display: inline-flex; flex: 1 1 auto; min-width: 0; align-items: baseline; gap: 4px; overflow: hidden; white-space: nowrap; }
.size-trigger-copy small { overflow: hidden; color: var(--text-muted); font-size: 9.5px; text-overflow: ellipsis; }
.pill--action > svg { flex: 0 0 auto; }

.batch-segmented { display: inline-flex; flex: 1 1 auto; min-width: 0; min-height: 0; justify-content: center; gap: 2px; overflow: visible; border: 0; border-radius: 0; background: transparent; }
.batch-segmented button {
  flex: 1 1 0; min-width: 0; min-height: 26px; padding: 0 5px; border: 1px solid transparent; border-radius: 999px;
  background: transparent; color: var(--text-secondary); font: inherit; font-size: 12px; white-space: nowrap; cursor: pointer;
}
.batch-segmented button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-strong); }
.batch-segmented button:disabled { opacity: .5; cursor: not-allowed; }
.batch-custom-count {
  width: 38px; height: 26px; padding: 0 6px; border: 1px solid var(--border); border-radius: 999px;
  background: transparent; color: var(--text-primary); font: 12px var(--font-mono); text-align: center;
}

.submit-row { display: flex; flex-direction: column; align-items: stretch; gap: 7px; margin-top: 2px; }
.primary-button {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  flex: 1 1 auto; width: auto; min-width: 150px; min-height: 46px; padding: 0 16px; border: 1px solid var(--accent); border-radius: 10px;
  background: var(--accent); color: var(--text-inverse); font: inherit; font-size: 14.5px; font-weight: 500; cursor: pointer;
  box-shadow: none; letter-spacing: 0; transition: background 160ms;
}
.primary-button:hover:not(:disabled) { background: var(--accent-strong); }
.primary-button:disabled { opacity: .5; cursor: not-allowed; }
.generate-panel .billing-estimate { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, auto); align-items: baseline; gap: 4px 12px; min-width: 0; max-width: 100%; box-sizing: border-box; margin: 0; padding: 0; border: 0; border-radius: 0; background: transparent; color: var(--text-secondary); }
.billing-estimate strong { min-width: 0; font: 500 12px/1.45 var(--font-mono); color: var(--text-primary); overflow-wrap: anywhere; }
.billing-estimate span { min-width: 0; font-size: 11px; color: var(--text-muted); line-height: 1.4; text-align: right; overflow-wrap: anywhere; }
.billing-estimate.insufficient strong { color: var(--error); }
.billing-estimate.insufficient span { color: var(--error); }
.foot-note { min-width: 0; margin: 0; font-size: 11.5px; line-height: 1.6; color: var(--text-muted); overflow-wrap: anywhere; }

.creation-notice { margin: 0; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.creation-submit-error { margin: 0; color: var(--error); font-size: 13px; line-height: 1.6; }
.creation-advanced summary {
  display: flex; min-width: 0; flex-wrap: wrap; justify-content: space-between; gap: 4px 10px; cursor: pointer;
  font-size: 11.5px; color: var(--text-muted);
}
.creation-advanced summary span { flex: none; margin-left: auto; font-family: var(--font-mono); }
.creation-final-prompt {
  margin-top: 8px; padding: 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-input); color: var(--text-secondary); font-size: 12px;
  white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7;
}
.generate-panel button:focus-visible, .generate-panel select:focus-visible, .generate-panel summary:focus-visible,
.size-picker-trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.size-picker-note { margin: 14px 0 0; font-size: 11.5px; color: var(--text-muted); line-height: 1.6; }

@media (max-width: 360px) {
  .parameter-pills { grid-template-columns: minmax(0, 1fr); }
  .pill { gap: 4px; padding-inline: 8px; font-size: 11.5px; }
  .pill-label { font-size: 10.5px; }
  .pill--quantity { gap: 4px; }
  .batch-segmented button { padding-inline: 2px; font-size: 11px; }
  .batch-custom-count { width: 34px; }
}
@media (pointer: coarse) {
  .prompt-textarea, .batch-custom-count { font-size: 16px; }
  .prompt-tool-button { min-height: 44px; }
}
</style>
