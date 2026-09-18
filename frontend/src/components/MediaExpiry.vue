<script setup lang="ts">
import { computed } from 'vue'
import { useMediaClock } from '@/composables/useMediaClock'
import { expiryText, mediaAvailable } from '@/lib/media-state'
const props = defineProps<{ state: string; expiresAt?: string | null; permanent?: boolean }>()
const now = useMediaClock()
const text = computed(() => expiryText(props.state, props.expiresAt, Boolean(props.permanent), now.value))
const urgent = computed(() => Boolean(props.expiresAt && mediaAvailable(props.state, props.expiresAt, now.value) && Date.parse(props.expiresAt) - now.value < 6 * 3600000))
</script>
<template><span class="media-expiry" :class="{ urgent }" :title="expiresAt ? new Date(expiresAt).toLocaleString('zh-CN') : text">{{ text }}</span></template>
<style scoped>
.media-expiry { display: block; color: var(--text-secondary); font-size: 12px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.urgent { color: var(--error); font-weight: 600; }
</style>
