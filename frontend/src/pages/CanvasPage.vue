<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus,
  Upload,
  LayoutGrid,
  ArrowUpRight,
  Cloud,
  HardDrive,
  Trash2,
  Download,
  Sparkles,
} from 'lucide-vue-next'
import CanvasEditor from '@/components/canvas/CanvasEditor.vue'
import { authState, fetchCurrentUser } from '@/lib/auth'
import { newProject } from '@/lib/canvas/model'
import type { CanvasProject } from '@/lib/canvas/model'
import {
  deleteProject,
  downloadBlob,
  exportProject,
  getProject,
  importProject,
  listProjects,
  saveProject,
} from '@/lib/canvas/storage'
import {
  cloudCapabilities,
  cloudProjects,
  deleteCloudProject,
  restoreCloudProject,
} from '@/lib/canvas/cloud'
import type { CloudCapabilities, CloudProject } from '@/lib/canvas/cloud'
const route = useRoute(),
  router = useRouter(),
  projects = ref<CanvasProject[]>([]),
  current = ref<CanvasProject>(),
  cloud = ref<CloudProject[]>([]),
  capabilities = ref<CloudCapabilities>(),
  feedback = ref(''),
  loading = ref(true),
  working = ref(false),
  importInput = ref<HTMLInputElement>(),
  tab = ref<'local' | 'cloud'>('local')
let generation = 0
async function load() {
  const version = ++generation
  loading.value = true
  feedback.value = ''
  try {
    if (!authState.user) await fetchCurrentUser()
    if (version !== generation) return
    const ownerId = authState.user?.id
    if (!ownerId) {
      await router.replace('/login')
      return
    }
    const id = typeof route.params.id === 'string' ? route.params.id : ''
    const result = id ? await getProject(ownerId, id) : undefined
    if (version !== generation || authState.user?.id !== ownerId) return
    current.value = result
    if (id && !result) {
      feedback.value =
        '此浏览器中没有这张画布。请返回列表导入项目，或从云端恢复。'
      return
    }
    projects.value = await listProjects(ownerId)
    try {
      const cap = await cloudCapabilities()
      if (version === generation) capabilities.value = cap
    } catch {
      capabilities.value = undefined
    }
  } catch (e) {
    feedback.value = (e as Error).message
  } finally {
    if (version === generation) loading.value = false
  }
}
async function action(fn: () => Promise<void>) {
  if (working.value) return
  working.value = true
  feedback.value = ''
  try {
    await fn()
  } catch (e) {
    feedback.value = (e as Error).message
  } finally {
    working.value = false
  }
}
function owner() {
  const id = authState.user?.id
  if (!id) throw new Error('请先登录。')
  return id
}
async function create() {
  await action(async () => {
    const p = newProject(owner())
    p.revision = await saveProject(p)
    await router.push(`/canvas/${p.id}`)
  })
}
async function importFile(file: File) {
  await action(async () => {
    const id = owner(),
      p = await importProject(file, id)
    if (owner() !== id) return
    await router.push(`/canvas/${p.id}`)
  })
}
async function remove(p: CanvasProject) {
  if (
    !window.confirm(
      `移除本地画布“${p.title}”？未被其他本地画布引用的素材也会移除。请先导出备份。`,
    )
  )
    return
  await action(async () => {
    await deleteProject(owner(), p.id)
    projects.value = await listProjects(owner())
  })
}
async function exportFile(p: CanvasProject) {
  await action(async () => {
    downloadBlob(await exportProject(p), `${p.title}.epcanvas.json`)
  })
}
async function showCloud() {
  tab.value = 'cloud'
  await action(async () => {
    cloud.value = await cloudProjects()
  })
}
async function restore(p: CloudProject) {
  await action(async () => {
    const id = owner(),
      assertOwner = () => {
        if (owner() !== id) throw new Error('登录状态已变化。')
      }
    const restored = await restoreCloudProject(p.id, id, assertOwner)
    assertOwner()
    await router.push(`/canvas/${restored.id}`)
  })
}
async function removeCloud(p: CloudProject) {
  if (
    !window.confirm(`删除云端画布“${p.title}”及其云端素材？本地副本不会删除。`)
  )
    return
  await action(async () => {
    await deleteCloudProject(p.id)
    cloud.value = await cloudProjects()
    capabilities.value = await cloudCapabilities()
  })
}
watch(
  () => route.params.id,
  () => {
    void load()
  },
)
watch(
  () => authState.token,
  () => {
    current.value = undefined
    projects.value = []
    cloud.value = []
    capabilities.value = undefined
    generation++
    if (!authState.token) void router.replace('/login')
    else void load()
  },
)
onMounted(() => {
  void load()
})
</script>
<template>
  <p v-if="loading" class="canvas-loading">正在打开画布…</p>
  <CanvasEditor
    v-else-if="current"
    :key="`${current.ownerId}:${current.id}`"
    :initial="current"
    :can-cloud="capabilities?.can_write === true"
  />
  <section v-else class="canvas-library">
    <div class="library-heading">
      <div>
        <span class="library-eyebrow">创作空间</span>
        <h1>无限画布<span>让每次尝试，成为下一次灵感</span></h1>
        <p>参考图、提示词和生成结果，在同一张画布里自由展开。</p>
      </div>
      <div class="library-actions">
        <button :disabled="working" @click="importInput?.click()">
          <Upload :size="16" />导入项目</button
        ><button class="primary" :disabled="working" @click="create">
          <Plus :size="17" />新建画布
        </button>
      </div>
    </div>
    <div class="library-tabs">
      <button :class="{ active: tab === 'local' }" @click="tab = 'local'">
        <HardDrive :size="16" />此浏览器
        <span>{{ projects.length }}</span></button
      ><button :class="{ active: tab === 'cloud' }" @click="showCloud">
        <Cloud :size="16" />云端画布 <small>VIP</small>
      </button>
    </div>
    <p v-if="feedback" class="library-feedback" role="alert">{{ feedback }}</p>
    <p v-if="route.params.id" class="library-feedback">
      <router-link to="/canvas">返回画布列表</router-link>
    </p>
    <template v-if="tab === 'local'">
      <div class="local-note">
        <HardDrive :size="16" /><span
          >画布和素材保存在此浏览器。清理网站数据会移除本地内容，请定期导出完整项目备份。</span
        >
      </div>
      <div class="project-grid">
        <button class="new-project-card" :disabled="working" @click="create">
          <span><Plus :size="25" /></span><strong>一张新的画布</strong
          ><small>从文字或图片开始</small>
        </button>
        <article v-for="p in projects" :key="p.id" class="project-card">
          <button class="project-open" @click="router.push(`/canvas/${p.id}`)">
            <div class="project-cover">
              <LayoutGrid :size="32" /><span>{{ p.nodes.length }} 个节点</span
              ><ArrowUpRight :size="18" class="open-arrow" />
            </div>
            <h2>{{ p.title || '未命名画布' }}</h2>
            <p>{{ new Date(p.updatedAt).toLocaleString('zh-CN') }}</p>
          </button>
          <div class="project-actions">
            <span><HardDrive :size="12" />本地画布</span
            ><button
              title="导出项目"
              aria-label="导出项目"
              :disabled="working"
              @click="exportFile(p)"
            >
              <Download :size="15" /></button
            ><button
              title="移除本地画布"
              aria-label="移除本地画布"
              :disabled="working"
              @click="remove(p)"
            >
              <Trash2 :size="15" />
            </button>
          </div>
        </article>
      </div>
    </template>
    <template v-else>
      <div class="local-note">
        <Cloud :size="16" /><span
          >{{
            capabilities?.can_write
              ? 'VIP 可在编辑器中保存到云端，在其他设备恢复。'
              : 'VIP 可保存到云端；已有云端画布仍可恢复、导出或删除。'
          }}<template v-if="capabilities">
            已使用 {{ (capabilities.used_bytes / 1024 / 1024).toFixed(1) }} /
            {{ capabilities.max_bytes / 1024 / 1024 }} MB。</template
          ></span
        >
      </div>
      <p v-if="!cloud.length" class="cloud-empty">
        <Cloud :size="32" />还没有云端画布。<span>本地画布始终可以使用。</span>
      </p>
      <div class="project-grid">
        <article v-for="p in cloud" :key="p.id" class="project-card">
          <div class="project-open">
            <div class="project-cover">
              <Cloud :size="32" /><span>版本 {{ p.version }}</span>
            </div>
            <h2>{{ p.title }}</h2>
            <p>{{ new Date(p.updated_at).toLocaleString('zh-CN') }}</p>
          </div>
          <div class="project-actions">
            <button :disabled="working" @click="restore(p)">
              恢复到此浏览器</button
            ><button
              title="删除云端画布"
              aria-label="删除云端画布"
              :disabled="working"
              @click="removeCloud(p)"
            >
              <Trash2 :size="15" />
            </button>
          </div>
        </article>
      </div>
    </template>
    <footer class="canvas-credit">
      <Sparkles :size="13" />交互与本地创作流程参考
      <a
        href="https://github.com/basketikun/infinite-canvas"
        target="_blank"
        rel="noopener noreferrer"
        >basketikun / infinite-canvas</a
      >
    </footer>
    <input
      ref="importInput"
      type="file"
      accept=".json,.epcanvas.json"
      hidden
      @change="
        (e) => {
          const input = e.target as HTMLInputElement
          if (input.files?.[0]) void importFile(input.files[0])
          input.value = ''
        }
      "
    />
  </section>
</template>
<style scoped>
.canvas-library {
  max-width: 1280px;
  margin: auto;
  padding: 24px 12px 50px;
}
.canvas-loading {
  text-align: center;
  padding: 100px;
  color: var(--text-muted);
}
.library-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 34px;
}
.library-eyebrow {
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 3px;
}
.library-heading h1 {
  font-weight: 500;
  font-size: 32px;
  margin: 10px 0;
}
.library-heading h1 span {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 400;
  margin-left: 20px;
}
.library-heading p {
  color: var(--text-secondary);
  font-size: 14px;
  margin: 0;
  line-height: 1.8;
}
.library-actions {
  display: flex;
  gap: 9px;
  flex-shrink: 0;
}
button {
  font: inherit;
  cursor: pointer;
  color: var(--text-primary);
}
button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.library-actions button {
  display: flex;
  align-items: center;
  gap: 7px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 11px 16px;
  font-size: 13px;
}
.library-actions .primary {
  background: var(--accent);
  color: var(--text-inverse);
  border-color: var(--accent);
}
.library-tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 20px;
}
.library-tabs button {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 0;
  border-bottom: 2px solid transparent;
  padding: 14px 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
}
.library-tabs button.active {
  border-bottom-color: var(--accent);
  color: var(--accent);
}
.library-tabs span,
.library-tabs small {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  background: var(--accent-soft);
}
.local-note {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.7;
  margin-bottom: 24px;
}
.local-note svg {
  flex-shrink: 0;
}
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 20px;
}
.project-card {
  overflow: hidden;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}
.project-card:hover {
  border-color: var(--border-accent);
  box-shadow: var(--shadow-md);
}
.project-open {
  display: block;
  width: 100%;
  border: 0;
  padding: 0;
  background: transparent;
  text-align: left;
}
.project-cover {
  position: relative;
  height: 145px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--accent);
  background-color: var(--bg-elevated);
  background-image: radial-gradient(var(--border-accent) 1px, transparent 1px);
  background-size: 16px 16px;
}
.project-cover span {
  font-size: 11px;
  color: var(--text-muted);
}
.open-arrow {
  position: absolute;
  right: 15px;
  top: 15px;
}
.project-open h2 {
  margin: 16px 17px 7px;
  font-size: 16px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-open p {
  margin: 0 17px 16px;
  font-size: 11px;
  color: var(--text-muted);
}
.project-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-top: 1px solid var(--border-subtle);
}
.project-actions span {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-right: auto;
  font-size: 11px;
  color: var(--text-muted);
}
.project-actions button {
  display: flex;
  align-items: center;
  border: 0;
  padding: 3px;
  background: transparent;
  font-size: 12px;
}
.project-actions button:first-child {
  margin-right: auto;
}
.new-project-card {
  min-height: 266px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border: 1px dashed var(--border-accent);
  border-radius: 14px;
  background: var(--accent-glow);
}
.new-project-card > span {
  display: grid;
  place-items: center;
  background: var(--accent-soft);
  border-radius: 12px;
  width: 50px;
  height: 50px;
  color: var(--accent);
}
.new-project-card strong {
  font-size: 14px;
  font-weight: 500;
}
.new-project-card small {
  font-size: 12px;
  color: var(--text-muted);
}
.library-feedback {
  padding: 12px;
  background: var(--error-soft);
  color: var(--error);
  border-radius: 8px;
  font-size: 13px;
}
.canvas-credit {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 45px;
  font-size: 11px;
  color: var(--text-muted);
}
.canvas-credit a {
  color: var(--text-secondary);
}
.cloud-empty {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 16px;
  padding: 60px;
  color: var(--text-secondary);
}
.cloud-empty span {
  font-size: 12px;
  color: var(--text-muted);
}
@media (max-width: 700px) {
  .canvas-library {
    padding: 16px 0;
  }
  .library-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 16px;
  }
  .library-heading h1 {
    font-size: 27px;
  }
  .library-heading h1 span {
    display: block;
    margin: 8px 0;
  }
  .project-grid {
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  }
}
</style>
