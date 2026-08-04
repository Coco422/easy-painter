<script setup lang="ts">
import {
  AlertCircle,
  ArrowUpCircle,
  CheckCircle2,
  ExternalLink,
  GitCommitHorizontal,
  Info,
  LoaderCircle,
  RefreshCw,
  X,
} from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { compareSemver, type ReleaseInfo } from '@/lib/release'
import {
  APP_RELEASES,
  APP_VERSION,
  fetchLatestGitHubRelease,
  REPOSITORY_URL,
  type RemoteReleaseInfo,
} from '@/lib/version'

type CheckState = 'idle' | 'checking' | 'current' | 'update' | 'ahead' | 'none' | 'error'

const open = ref(false)
const checkState = ref<CheckState>('idle')
const remoteRelease = ref<RemoteReleaseInfo | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const dialogRef = ref<HTMLElement | null>(null)
let requestController: AbortController | null = null
let previousBodyOverflow = ''

const localReleases = APP_RELEASES.filter((release) => release.version !== 'Unreleased')
const latestVersion = computed(() => remoteRelease.value?.version ?? '')
const hasNewVersion = computed(() => (
  remoteRelease.value ? compareSemver(remoteRelease.value.version, APP_VERSION) > 0 : false
))
const latestVersionLabel = computed(() => {
  if (checkState.value === 'checking') return '查询中…'
  if (checkState.value === 'none') return '暂无'
  if (checkState.value === 'error' || checkState.value === 'idle') return '—'
  return latestVersion.value || '—'
})
const releases = computed<ReleaseInfo[]>(() => {
  const remote = remoteRelease.value
  if (!remote || !remote.hasFormattedNotes || compareSemver(remote.version, APP_VERSION) <= 0) {
    return localReleases
  }
  if (localReleases.some((release) => release.version === remote.version)) return localReleases
  return [remote, ...localReleases]
})
const checkMessage = computed(() => {
  if (checkState.value === 'checking') return '正在读取 GitHub 最新正式 Release…'
  if (checkState.value === 'update') return `发现新版本 ${latestVersion.value}`
  if (checkState.value === 'current') return '当前已是最新正式版本'
  if (checkState.value === 'ahead') return `当前构建版本高于最新正式版本 ${latestVersion.value}`
  if (checkState.value === 'none') return '仓库尚未发布正式 Release'
  if (checkState.value === 'error') return '暂时无法获取 GitHub 版本信息，已继续使用内置更新日志'
  return ''
})

function releaseTypeClass(type: string) {
  if (type === '新增') return 'is-added'
  if (type === '修复') return 'is-fixed'
  if (type === '调整') return 'is-changed'
  if (type === '安全') return 'is-security'
  if (type === '文档') return 'is-documentation'
  return 'is-improved'
}

function closeDialog() {
  open.value = false
  nextTick(() => triggerRef.value?.focus())
}

function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialogRef.value) return
  const focusable = Array.from(dialogRef.value.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
  ))
  if (focusable.length === 0) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeDialog()
    return
  }
  trapFocus(event)
}

async function openDialog() {
  open.value = true
  await nextTick()
  dialogRef.value?.focus()
  void checkForUpdates()
}

async function checkForUpdates() {
  if (checkState.value === 'checking') return
  requestController?.abort()
  requestController = new AbortController()
  checkState.value = 'checking'
  remoteRelease.value = null

  try {
    const result = await fetchLatestGitHubRelease(requestController.signal)
    if (result.status === 'none') {
      checkState.value = 'none'
      return
    }

    remoteRelease.value = result.release
    const comparison = compareSemver(result.release.version, APP_VERSION)
    if (comparison > 0) checkState.value = 'update'
    else if (comparison < 0) checkState.value = 'ahead'
    else checkState.value = 'current'
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    checkState.value = 'error'
  }
}

watch(open, (isOpen) => {
  if (isOpen) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeydown)
  } else {
    document.body.style.overflow = previousBodyOverflow
    window.removeEventListener('keydown', handleKeydown)
  }
})

onBeforeUnmount(() => {
  requestController?.abort()
  document.body.style.overflow = previousBodyOverflow
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <button ref="triggerRef" type="button" class="version-trigger" title="查看版本更新" @click="openDialog">
    <GitCommitHorizontal :size="14" aria-hidden="true" />
    <span>{{ APP_VERSION }}</span>
    <i v-if="hasNewVersion" aria-label="有新版本" />
  </button>

  <Teleport to="body">
    <Transition name="version-dialog">
      <div v-if="open" class="version-dialog-backdrop" @click.self="closeDialog">
        <section
          ref="dialogRef"
          class="version-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="version-dialog-title"
          tabindex="-1"
        >
          <header class="version-dialog-header">
            <div>
              <p class="version-dialog-kicker">Release history</p>
              <h2 id="version-dialog-title">版本更新</h2>
              <span>发布说明由仓库根目录 CHANGELOG.md 统一维护。</span>
            </div>
            <button type="button" aria-label="关闭版本更新" @click="closeDialog"><X :size="18" /></button>
          </header>

          <div class="version-summary-grid">
            <div class="version-summary-card">
              <small>当前构建</small>
              <strong>{{ APP_VERSION }}</strong>
            </div>
            <div class="version-summary-card">
              <div class="version-latest-label">
                <small>最新正式版</small>
                <button type="button" :disabled="checkState === 'checking'" @click="checkForUpdates">
                  <RefreshCw :size="12" :class="{ spinning: checkState === 'checking' }" aria-hidden="true" />
                  {{ checkState === 'checking' ? '检查中' : '重新检查' }}
                </button>
              </div>
              <strong>{{ latestVersionLabel }}</strong>
            </div>
          </div>

          <div
            v-if="checkMessage"
            class="version-check-result"
            :class="`is-${checkState}`"
            role="status"
            aria-live="polite"
          >
            <LoaderCircle v-if="checkState === 'checking'" :size="15" class="spinning" aria-hidden="true" />
            <ArrowUpCircle v-else-if="checkState === 'update'" :size="15" aria-hidden="true" />
            <CheckCircle2 v-else-if="checkState === 'current'" :size="15" aria-hidden="true" />
            <Info v-else-if="checkState === 'ahead' || checkState === 'none'" :size="15" aria-hidden="true" />
            <AlertCircle v-else :size="15" aria-hidden="true" />
            <span>{{ checkMessage }}</span>
            <a
              v-if="checkState === 'update' && remoteRelease"
              :href="remoteRelease.url"
              target="_blank"
              rel="noopener noreferrer"
            >
              查看 Release <ExternalLink :size="12" aria-hidden="true" />
            </a>
          </div>
          <p v-if="remoteRelease && !remoteRelease.hasFormattedNotes" class="version-notes-warning">
            远端发布说明未使用 CHANGELOG 条目格式，因此时间线继续展示当前构建内置记录。
          </p>
          <p class="version-check-note">仅只读检查 GitHub Releases，不会下载文件或自动升级；部署新版本时应同时更新前后端。</p>

          <div class="version-timeline" aria-label="版本记录">
            <article v-for="release in releases" :key="release.version" class="version-release">
              <span class="version-timeline-dot" aria-hidden="true" />
              <header>
                <strong>{{ release.version }}</strong>
                <time v-if="release.date">{{ release.date }}</time>
                <span v-if="release.version === latestVersion" class="version-badge is-latest">最新</span>
                <span v-if="release.version === APP_VERSION" class="version-badge">当前</span>
              </header>
              <ul>
                <li v-for="(item, index) in release.items" :key="`${release.version}-${index}`">
                  <span class="release-type" :class="releaseTypeClass(item.type)">{{ item.type }}</span>
                  <p>{{ item.content }}</p>
                </li>
              </ul>
            </article>
          </div>

          <footer class="version-dialog-footer">
            <a :href="`${REPOSITORY_URL}/blob/main/CHANGELOG.md`" target="_blank" rel="noopener noreferrer">
              完整更新日志 <ExternalLink :size="13" aria-hidden="true" />
            </a>
            <a :href="`${REPOSITORY_URL}/blob/main/ROADMAP.md`" target="_blank" rel="noopener noreferrer">
              Roadmap <ExternalLink :size="13" aria-hidden="true" />
            </a>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.version-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 30px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  font: 600 11px/1 var(--font-mono);
  white-space: nowrap;
  transition: color 160ms, border-color 160ms, background 160ms;
}

.version-trigger:hover,
.version-trigger:focus-visible {
  border-color: var(--border);
  background: var(--bg-hover);
  color: var(--text-primary);
}

.version-trigger i {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--success);
}

.version-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(5, 5, 6, 0.72);
  backdrop-filter: blur(6px);
}

.version-dialog {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: min(780px, calc(100vh - 48px));
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-surface);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.28);
  outline: none;
}

.version-dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 22px 0;
}

.version-dialog-kicker {
  margin: 0 0 7px;
  color: var(--accent);
  font: 600 10px/1 var(--font-mono);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.version-dialog-header h2 {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 22px;
}

.version-dialog-header span {
  display: block;
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.version-dialog-header > button {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  transition: color 160ms, border-color 160ms, background 160ms;
}

.version-dialog-header > button:hover,
.version-dialog-header > button:focus-visible {
  border-color: var(--border-accent);
  background: var(--bg-hover);
  color: var(--text-primary);
}

.version-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 18px 22px 0;
}

.version-summary-card {
  min-width: 0;
  padding: 12px 13px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-elevated);
}

.version-summary-card small {
  color: var(--text-muted);
  font-size: 11px;
}

.version-summary-card strong {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: var(--text-primary);
  font: 700 15px/1.3 var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-latest-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.version-latest-label button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 10px;
}

.version-latest-label button:hover:not(:disabled),
.version-latest-label button:focus-visible {
  color: var(--accent);
}

.version-check-result {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  margin: 10px 22px 0;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 11px;
}

.version-check-result > span {
  min-width: 0;
  flex: 1;
}

.version-check-result.is-update,
.version-check-result.is-current {
  border-color: rgba(74, 143, 102, 0.22);
  background: var(--success-soft);
  color: var(--success);
}

.version-check-result.is-error {
  border-color: rgba(180, 72, 72, 0.2);
  background: var(--error-soft);
  color: var(--error);
}

.version-check-result a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
  color: inherit;
  font-weight: 700;
}

.version-check-result a:hover,
.version-check-result a:focus-visible {
  text-decoration: underline;
  text-underline-offset: 2px;
}

.version-notes-warning,
.version-check-note {
  margin: 9px 22px 0;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.55;
}

.version-notes-warning {
  color: var(--accent-strong);
}

.version-timeline {
  min-height: 120px;
  flex: 1 1 auto;
  margin-top: 15px;
  padding: 0 22px 8px 34px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

.version-release {
  position: relative;
  padding: 0 0 22px 18px;
  border-left: 1px solid var(--border);
}

.version-release:last-child {
  padding-bottom: 4px;
}

.version-timeline-dot {
  position: absolute;
  top: 5px;
  left: -5px;
  width: 9px;
  height: 9px;
  border: 2px solid var(--bg-surface);
  border-radius: 999px;
  background: var(--text-muted);
  box-shadow: 0 0 0 1px var(--border);
}

.version-release:first-child .version-timeline-dot {
  background: var(--accent);
}

.version-release > header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.version-release > header strong {
  color: var(--text-primary);
  font: 700 13px/1.4 var(--font-mono);
}

.version-release time {
  color: var(--text-muted);
  font-size: 11px;
}

.version-badge {
  padding: 2px 5px;
  border-radius: 3px;
  background: var(--bg-hover);
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 700;
}

.version-badge.is-latest {
  background: var(--success-soft);
  color: var(--success);
}

.version-release ul {
  display: grid;
  gap: 7px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.version-release li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 8px;
}

.version-release li p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.release-type {
  min-width: 30px;
  padding: 2px 5px;
  border-radius: 3px;
  background: var(--bg-hover);
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 700;
  text-align: center;
}

.release-type.is-added { background: var(--success-soft); color: var(--success); }
.release-type.is-fixed { background: var(--error-soft); color: var(--error); }
.release-type.is-changed { background: var(--accent-soft); color: var(--accent); }
.release-type.is-security { background: rgba(160, 112, 82, 0.12); color: #b87543; }
.release-type.is-documentation { background: rgba(116, 105, 151, 0.12); color: #8174a7; }

.version-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 14px;
  padding: 12px 22px;
  border-top: 1px solid var(--border);
}

.version-dialog-footer a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-muted);
  font-size: 11px;
  text-decoration: none;
}

.version-dialog-footer a:hover,
.version-dialog-footer a:focus-visible {
  color: var(--accent);
}

.spinning { animation: version-spin 800ms linear infinite; }
@keyframes version-spin { to { transform: rotate(360deg); } }

.version-dialog-enter-active,
.version-dialog-leave-active { transition: opacity 160ms cubic-bezier(0.25, 0.46, 0.45, 0.94); }
.version-dialog-enter-active .version-dialog,
.version-dialog-leave-active .version-dialog { transition: transform 160ms cubic-bezier(0.25, 0.46, 0.45, 0.94); }
.version-dialog-enter-from,
.version-dialog-leave-to { opacity: 0; }
.version-dialog-enter-from .version-dialog,
.version-dialog-leave-to .version-dialog { transform: translateY(6px); }

@media (max-width: 620px) {
  .version-trigger { min-height: 28px; padding-inline: 6px; font-size: 10px; }
  .version-dialog-backdrop { align-items: end; padding: 0; }
  .version-dialog { width: 100%; max-height: 88vh; border-right: 0; border-bottom: 0; border-left: 0; border-radius: 6px 6px 0 0; }
  .version-dialog-header { padding: 18px 16px 0; }
  .version-summary-grid { padding: 16px 16px 0; }
  .version-check-result, .version-notes-warning, .version-check-note { margin-inline: 16px; }
  .version-timeline { padding-right: 16px; padding-left: 27px; }
  .version-dialog-footer { padding-inline: 16px; }
}

@media (max-width: 390px) {
  .version-summary-grid { grid-template-columns: 1fr; }
  .version-dialog-header h2 { font-size: 20px; }
  .version-check-result { align-items: flex-start; flex-wrap: wrap; }
  .version-check-result a { width: 100%; padding-left: 22px; }
}

@media (prefers-reduced-motion: reduce) {
  .version-trigger,
  .version-dialog-header > button,
  .version-dialog-enter-active,
  .version-dialog-leave-active,
  .version-dialog-enter-active .version-dialog,
  .version-dialog-leave-active .version-dialog { transition: none; }
  .spinning { animation: none; }
}
</style>
