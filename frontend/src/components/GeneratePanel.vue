<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import type { ImageAspectRatio, PublicModel } from '@/lib/types'

const props = defineProps<{
  prompt: string
  selectedModel: string
  selectedAspectRatio: ImageAspectRatio
  referenceImage: File | null
  models: PublicModel[]
  maxLength: number
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:prompt': [value: string]
  'update:model': [value: string]
  'update:aspect-ratio': [value: ImageAspectRatio]
  'update:reference-image': [value: File | null]
  submit: []
}>()

const promptLength = computed(() => props.prompt.length)
const aspectRatios: Array<{ value: ImageAspectRatio; label: string }> = [
  { value: 'auto', label: '自动' },
  { value: '1:1', label: '方形 1:1' },
  { value: '3:4', label: '竖版 3:4' },
  { value: '9:16', label: '故事 9:16' },
  { value: '4:3', label: '横屏 4:3' },
  { value: '16:9', label: '宽屏 16:9' },
]
const previewUrl = ref<string | null>(null)

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
</script>

<template>
  <div class="generate-panel" id="create">
    <textarea
      :value="prompt"
      class="prompt-textarea"
      :maxlength="maxLength"
      placeholder="请输入画面描述"
      @input="emit('update:prompt', ($event.target as HTMLTextAreaElement).value)"
    />

    <div class="reference-uploader">
      <label class="reference-upload-button">
        <input type="file" accept="image/png,image/jpeg,image/webp" @change="handleReferenceImageChange" />
        <span>参考图</span>
      </label>

      <div v-if="referenceImage && previewUrl" class="reference-preview">
        <img :src="previewUrl" :alt="referenceImage.name" />
        <span>{{ referenceImage.name }}</span>
        <button type="button" @click="emit('update:reference-image', null)">清除</button>
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
        <span>比例</span>
        <select
          :value="selectedAspectRatio"
          class="model-select"
          @change="emit('update:aspect-ratio', ($event.target as HTMLSelectElement).value as ImageAspectRatio)"
        >
          <option v-for="ratio in aspectRatios" :key="ratio.value" :value="ratio.value">
            {{ ratio.label }}
          </option>
        </select>
      </label>

      <button class="primary-button" :disabled="submitting" @click="handleSubmit">
        {{ submitting ? '正在提交...' : '开始创作' }}
      </button>
    </div>

    <div class="panel-footer">
      <p class="char-count">{{ promptLength }} / {{ maxLength }}</p>
    </div>
  </div>
</template>
