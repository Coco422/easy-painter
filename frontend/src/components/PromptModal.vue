<script setup lang="ts">
import { computed } from 'vue'

import type { GalleryItem } from '@/lib/types'

const props = defineProps<{
  item: GalleryItem | null
}>()

const emit = defineEmits<{
  close: []
}>()

const open = computed(() => Boolean(props.item))

function closeModal() {
  emit('close')
}
</script>

<template>
  <div v-if="open && item" class="modal-backdrop" @click.self="closeModal">
    <div class="modal-panel">
      <button class="modal-close" type="button" @click="closeModal">关闭</button>
      <img :src="item.image_url" :alt="item.prompt" class="modal-image" />
      <div class="modal-copy">
        <p class="section-label">提示词</p>
        <p class="modal-prompt">{{ item.prompt }}</p>

        <template v-if="item.revised_prompt">
          <p class="section-label">模型修订提示词</p>
          <p class="modal-revised">{{ item.revised_prompt }}</p>
        </template>

        <div class="modal-meta">
          <span>{{ item.model }}</span>
          <span>{{ new Date(item.finished_at).toLocaleString('zh-CN') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
