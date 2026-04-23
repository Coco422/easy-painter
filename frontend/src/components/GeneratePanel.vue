<script setup lang="ts">
import { computed } from 'vue'

import type { PublicModel } from '@/lib/types'

const props = defineProps<{
  prompt: string
  selectedModel: string
  models: PublicModel[]
  examplePrompts: string[]
  maxLength: number
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:prompt': [value: string]
  'update:model': [value: string]
  submit: []
  pickExample: [value: string]
}>()

const promptLength = computed(() => props.prompt.length)

function handleSubmit() {
  emit('submit')
}
</script>

<template>
  <div class="generate-panel" id="create">
    <div class="panel-topline">
      <span>仅支持文生图</span>
      <span>同一 IP 每分钟最多 2 次</span>
    </div>

    <textarea
      :value="prompt"
      class="prompt-textarea"
      :maxlength="maxLength"
      placeholder="描述一幅你想看到的画面，例如：春天傍晚的湖边小镇，暖灯、薄雾和回家的小船。"
      @input="emit('update:prompt', ($event.target as HTMLTextAreaElement).value)"
    />

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

      <button class="primary-button" :disabled="submitting" @click="handleSubmit">
        {{ submitting ? '正在提交...' : '开始创作' }}
      </button>
    </div>

    <div class="panel-footer">
      <p class="char-count">{{ promptLength }} / {{ maxLength }}</p>
      <div class="example-list">
        <button
          v-for="example in examplePrompts"
          :key="example"
          class="example-chip"
          type="button"
          @click="emit('pickExample', example)"
        >
          {{ example }}
        </button>
      </div>
    </div>
  </div>
</template>
