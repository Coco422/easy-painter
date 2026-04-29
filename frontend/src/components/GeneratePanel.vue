<script setup lang="ts">
import { FileImage, UploadCloud, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import type { BatchCount, ImageSize, PublicModel } from '@/lib/types'

const props = defineProps<{
  prompt: string
  selectedModel: string
  selectedSize: ImageSize
  selectedBatchCount: BatchCount
  referenceImage: File | null
  models: PublicModel[]
  maxLength: number
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:prompt': [value: string]
  'update:model': [value: string]
  'update:size': [value: ImageSize]
  'update:batch-count': [value: BatchCount]
  'update:reference-image': [value: File | null]
  submit: []
}>()

const promptLength = computed(() => props.prompt.length)
const sizeOptions: Array<{ value: ImageSize; label: string }> = [
  { value: 'auto', label: '自动' },
  { value: '1024x1024', label: '1024 x 1024 方图' },
  { value: '1536x1024', label: '1536 x 1024 横图' },
  { value: '1024x1536', label: '1024 x 1536 竖图' },
  { value: '2048x2048', label: '2048 x 2048 2K 方图' },
  { value: '2048x1152', label: '2048 x 1152 2K 横图' },
  { value: '1152x2048', label: '1152 x 2048 2K 竖图' },
  { value: '3840x2160', label: '3840 x 2160 4K 横图' },
  { value: '2160x3840', label: '2160 x 3840 4K 竖图' },
]
const batchOptions: BatchCount[] = [1, 2, 4]
const previewUrl = ref<string | null>(null)
const referenceMeta = computed(() => {
  if (!props.referenceImage) return ''
  const sizeInMb = props.referenceImage.size / 1024 / 1024
  return sizeInMb >= 1 ? `${sizeInMb.toFixed(1)} MB` : `${Math.max(1, Math.round(props.referenceImage.size / 1024))} KB`
})

watch(
  () => props.referenceImage,
  (file) => {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
      previewUrl.value = null
    }
    if (file) {
      previewUrl.value = URL.createObjectURL(file)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
})

function handleSubmit() {
  emit('submit')
}

function handleReferenceImageChange(event: Event) {
  const input = event.target as HTMLInputElement
  emit('update:reference-image', input.files?.[0] ?? null)
  input.value = ''
}

function clearReferenceImage() {
  emit('update:reference-image', null)
}
</script>

<template>
  <div class="generate-panel" id="create">
    <div class="prompt-stack">
      <div class="panel-topline">
        <span class="section-label">创作提示</span>
        <p class="char-count">{{ promptLength }} / {{ maxLength }}</p>
      </div>
      <textarea
        :value="prompt"
        class="prompt-textarea"
        :maxlength="maxLength"
        placeholder="请输入画面描述"
        @input="emit('update:prompt', ($event.target as HTMLTextAreaElement).value)"
      />
    </div>

    <div class="reference-uploader">
      <label class="reference-upload-dropzone">
        <input type="file" accept="image/png,image/jpeg,image/webp" @change="handleReferenceImageChange" />
        <span class="upload-logo" aria-hidden="true">
          <UploadCloud :size="24" />
        </span>
        <span class="upload-copy">
          <strong>上传参考图</strong>
          <small>PNG / JPG / WebP</small>
        </span>
      </label>

      <div v-if="referenceImage && previewUrl" class="reference-preview">
        <img :src="previewUrl" :alt="referenceImage.name" />
        <span class="reference-file">
          <FileImage :size="16" />
          <span>
            <strong>{{ referenceImage.name }}</strong>
            <small>{{ referenceMeta }}</small>
          </span>
        </span>
        <button type="button" title="清除参考图" aria-label="清除参考图" @click="clearReferenceImage">
          <X :size="18" />
        </button>
      </div>
    </div>

    <div class="panel-actions">
      <label class="field-label">
        <span>模型</span>
        <select
          :value="selectedModel"
          class="model-select"
          @change="emit('update:model', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="model in models" :key="model.id" :value="model.id" :disabled="!model.enabled">
            {{ model.label }}
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
          <option v-for="option in sizeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
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
