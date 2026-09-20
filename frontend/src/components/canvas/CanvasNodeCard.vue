<script setup lang="ts">
import { computed } from 'vue'
import {
  Image,
  Sparkles,
  StickyNote,
  Layers,
  GripHorizontal,
  ArrowRight,
} from 'lucide-vue-next'
import type { CanvasNode, CanvasRun } from '@/lib/canvas/model'
import type { PublicModel } from '@/lib/types'
const props = defineProps<{
  node: CanvasNode
  selected: boolean
  image?: string
  run?: CanvasRun
  models: PublicModel[]
  busy: boolean
  inputCount: number
  connecting: boolean
  connectionSource: boolean
  connectionTarget: boolean
}>()
const emit = defineEmits<{
  select: [event: PointerEvent]
  drag: [event: PointerEvent]
  resize: [event: PointerEvent]
  edit: []
  checkpoint: []
  generate: []
  retry: []
  derive: []
  connect: [event: PointerEvent | MouseEvent]
  connectTarget: []
}>()
const enabledModels = computed(() => props.models.filter((m) => m.enabled))
const model = computed(() =>
  enabledModels.value.find((m) => m.id === props.node.model),
)
const sizes = computed(() =>
  model.value?.supported_sizes.length ? model.value.supported_sizes : ['auto'],
)
const status = computed(() =>
  props.run
    ? {
        preparing: '准备任务',
        submitting: '正在提交',
        queued: '排队中',
        processing: '正在生成',
        succeeded: '已生成',
        failed: '生成失败',
        unknown: '提交结果待确认',
      }[props.run.status]
    : '',
)
function selectModel() {
  props.node.size = model.value?.supported_sizes[0] ?? 'auto'
  emit('edit')
}
</script>
<template>
  <article
    class="canvas-node"
    :class="[
      {
        selected,
        'is-group': node.type === 'group',
        'connection-source': connectionSource,
        'connection-target': connectionTarget,
      },
      `kind-${node.type}`,
    ]"
    :style="{
      left: `${node.x}px`,
      top: `${node.y}px`,
      width: `${node.width}px`,
      height: `${node.height}px`,
    }"
    :data-node-id="node.id"
    @pointerdown.stop="emit('select', $event)"
  >
    <header @pointerdown.stop="emit('drag', $event)">
      <component
        :is="
          node.type === 'image'
            ? Image
            : node.type === 'generation'
              ? Sparkles
              : node.type === 'group'
                ? Layers
                : StickyNote
        "
        :size="14"
      />
      <input
        v-model="node.title"
        aria-label="节点名称"
        maxlength="120"
        @pointerdown.stop
        @focus="emit('checkpoint')"
        @input="emit('edit')"
      />
      <GripHorizontal :size="15" class="drag-grip" />
    </header>
    <template v-if="node.type === 'text'">
      <textarea
        v-model="node.text"
        aria-label="笔记内容"
        placeholder="写下灵感、提示词，或这次想修改的地方…"
        maxlength="20000"
        @pointerdown.stop
        @focus="emit('checkpoint')"
        @input="emit('edit')"
      />
    </template>
    <template v-else-if="node.type === 'image'">
      <div class="node-image" @pointerdown.stop="emit('drag', $event)">
        <img v-if="image" :src="image" :alt="node.title" draggable="false" />
        <div v-else class="node-placeholder">
          <Image :size="28" /><span>{{ status || '素材未加载' }}</span
          ><small v-if="run?.error || run?.mediaError">{{
            run.error || run.mediaError
          }}</small>
        </div>
      </div>
      <div v-if="selected" class="node-actions" @pointerdown.stop>
        <button v-if="image" @click="emit('derive')">
          继续创作 <ArrowRight :size="13" />
        </button>
        <button
          v-if="
            run &&
            (['unknown', 'submitting', 'preparing'].includes(run.status) ||
              (run.status === 'succeeded' && !image))
          "
          @click="emit('retry')"
        >
          {{ run.status === 'succeeded' ? '获取图片' : '确认任务' }}
        </button>
      </div>
    </template>
    <template v-else-if="node.type === 'generation'">
      <div class="node-generator" @pointerdown.stop>
        <span class="input-summary">{{
          inputCount
            ? `${inputCount} 张参考图 · 按连线顺序`
            : '文字生成 · 可连接参考图片'
        }}</span>
        <textarea
          v-model="node.prompt"
          aria-label="生成提示词"
          placeholder="描述画面，或说明如何修改参考图…"
          maxlength="20000"
          @focus="emit('checkpoint')"
          @input="emit('edit')"
        />
        <select
          v-model="node.model"
          aria-label="生成模型"
          @focus="emit('checkpoint')"
          @change="selectModel"
        >
          <option value="" disabled>选择模型</option>
          <option v-for="m in enabledModels" :key="m.id" :value="m.id">
            {{ m.label }}
          </option>
        </select>
        <div class="generator-options">
          <select
            v-model="node.size"
            aria-label="图片尺寸"
            @focus="emit('checkpoint')"
            @change="emit('edit')"
          >
            <option v-for="size in sizes" :key="size" :value="size">
              {{ size === 'auto' ? '自动尺寸' : size }}
            </option></select
          ><select
            v-model.number="node.count"
            aria-label="生成数量"
            @focus="emit('checkpoint')"
            @change="emit('edit')"
          >
            <option :value="1">1 张</option>
            <option :value="2">2 张</option>
            <option :value="4">4 张</option>
          </select>
        </div>
        <button
          class="canvas-primary"
          :disabled="busy || !model"
          @click="emit('generate')"
        >
          <Sparkles :size="14" />{{ busy ? '正在提交…' : '生成图片'
          }}<span v-if="model"
            >{{ model.credit_cost * (node.count ?? 1) }} 丝</span
          >
        </button>
      </div>
    </template>
    <button
      v-if="node.type !== 'generation'"
      class="node-port"
      title="拖动或点击，连接到生成节点"
      aria-label="连接到生成节点"
      @pointerdown.stop="emit('connect', $event)"
      @click.stop="$event.detail === 0 && emit('connect', $event)"
    />
    <button
      v-else-if="connecting"
      class="connection-drop-target"
      aria-label="连接到此生成节点"
      @pointerdown.stop
      @click.stop="emit('connectTarget')"
    >
      <span class="node-input-port" />
    </button>
    <button
      v-if="selected"
      class="node-resize"
      title="调整节点大小"
      aria-label="调整节点大小"
      @pointerdown.stop="emit('resize', $event)"
    />
  </article>
</template>
<style scoped>
.canvas-node {
  position: absolute;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  color: var(--text-primary);
  pointer-events: auto;
  user-select: none;
}
.canvas-node.selected {
  border-color: var(--accent);
  box-shadow:
    0 0 0 2px var(--accent-soft),
    var(--shadow-md);
}
.canvas-node.connection-target {
  border-color: var(--accent);
  box-shadow:
    0 0 0 3px var(--accent-soft),
    var(--shadow-md);
}
header {
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border);
  cursor: grab;
  color: var(--text-secondary);
}
header input {
  border: 0;
  background: transparent;
  min-width: 0;
  flex: 1;
  color: inherit;
  font: inherit;
  font-size: 12px;
  padding: 3px;
  outline: none;
}
.drag-grip {
  opacity: 0.4;
}
textarea,
select {
  font: inherit;
  color: var(--text-primary);
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px;
  outline: none;
  min-width: 0;
}
textarea:focus,
select:focus {
  border-color: var(--accent);
}
.kind-text > textarea {
  flex: 1;
  margin: 12px;
  resize: none;
  line-height: 1.7;
  font-size: 14px;
  background: transparent;
  border: 0;
}
.node-image {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border-radius: 0 0 14px 14px;
  cursor: grab;
  background: var(--bg-elevated);
}
.node-image img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
}
.node-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 18px;
  gap: 10px;
  color: var(--text-muted);
  font-size: 13px;
}
.node-placeholder small {
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.node-generator {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  padding: 12px;
  gap: 9px;
  font-size: 12px;
}
.node-generator textarea {
  flex: 1;
  resize: none;
  min-height: 55px;
}
.input-summary {
  color: var(--text-muted);
  font-size: 11px;
}
.generator-options {
  display: flex;
  gap: 7px;
}
.generator-options select:first-child {
  flex: 1;
}
.canvas-primary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 0;
  border-radius: 8px;
  padding: 10px;
  background: var(--accent);
  color: var(--text-inverse);
  cursor: pointer;
}
.canvas-primary span {
  margin-left: auto;
  font-size: 11px;
}
.canvas-primary:disabled {
  opacity: 0.5;
  cursor: default;
}
.node-actions {
  position: absolute;
  bottom: -41px;
  left: 0;
  display: flex;
  gap: 6px;
}
.node-actions button {
  display: flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--bg-surface);
  padding: 7px 12px;
  color: var(--text-primary);
  font: inherit;
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}
.node-port {
  position: absolute;
  right: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: crosshair;
  touch-action: none;
}
.node-port::after,
.node-input-port {
  content: '';
  position: absolute;
  width: 12px;
  height: 12px;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  border: 2px solid var(--bg-surface);
  border-radius: 50%;
  background: var(--accent);
}
.node-port:hover::after,
.node-port:focus-visible::after,
.connection-source .node-port::after,
.connection-target .node-input-port {
  box-shadow: 0 0 0 4px var(--accent-soft);
}
.connection-drop-target {
  position: absolute;
  inset: 0;
  z-index: 1;
  border: 1px dashed var(--accent);
  border-radius: inherit;
  background: transparent;
  cursor: crosshair;
}
.node-input-port {
  left: 0;
}
.node-resize {
  position: absolute;
  right: 1px;
  bottom: 1px;
  width: 14px;
  height: 14px;
  border: 0;
  background: linear-gradient(
    135deg,
    transparent 45%,
    var(--accent) 46%,
    var(--accent) 58%,
    transparent 59%
  );
  cursor: nwse-resize;
}
.is-group {
  background: var(--accent-glow);
  border: 1px dashed var(--accent);
  box-shadow: none;
}
.is-group header {
  border-bottom: 0;
}
</style>
