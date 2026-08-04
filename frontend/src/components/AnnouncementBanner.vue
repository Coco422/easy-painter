<script setup lang="ts">
import { ArrowRight, CircleAlert, Info, TriangleAlert } from 'lucide-vue-next'
import { ref, watch } from 'vue'

import { fetchAnnouncements } from '@/lib/api'
import { authState } from '@/lib/auth'
import type { AnnouncementItem } from '@/lib/types'

const announcements = ref<AnnouncementItem[]>([])

async function loadAnnouncements() {
  try {
    announcements.value = await fetchAnnouncements()
  } catch {
    announcements.value = []
  }
}

watch(
  () => [authState.token, authState.user?.email] as const,
  () => { void loadAnnouncements() },
  { immediate: true },
)
</script>

<template>
  <section v-if="announcements.length" class="announcement-stack" aria-label="系统通知" aria-live="polite">
    <article
      v-for="announcement in announcements"
      :key="announcement.id"
      class="announcement-banner"
      :class="`announcement-${announcement.level}`"
    >
      <Info v-if="announcement.level === 'info'" :size="17" aria-hidden="true" />
      <TriangleAlert v-else-if="announcement.level === 'warning'" :size="17" aria-hidden="true" />
      <CircleAlert v-else :size="17" aria-hidden="true" />
      <div class="announcement-copy">
        <strong>{{ announcement.title }}</strong>
        <span>{{ announcement.content }}</span>
      </div>
      <router-link
        v-if="announcement.audience === 'unbound_email' && authState.user && !authState.user.email"
        to="/profile"
        class="announcement-action"
      >
        去绑定邮箱
        <ArrowRight :size="14" aria-hidden="true" />
      </router-link>
    </article>
  </section>
</template>

<style scoped>
.announcement-stack {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 8px;
  max-width: 1200px;
  margin: 12px auto 0;
  padding: 0 24px;
}

.announcement-banner {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-secondary);
  box-shadow: var(--shadow-sm);
}

.announcement-info { border-color: var(--border-accent); color: var(--accent); }
.announcement-warning { border-color: var(--border-accent); background: var(--accent-glow); color: var(--accent); }
.announcement-critical { border-color: color-mix(in srgb, var(--error) 34%, transparent); background: var(--error-soft); color: var(--error); }

.announcement-copy {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.announcement-copy strong {
  flex: 0 0 auto;
  color: var(--text-primary);
  font-size: 13px;
}

.announcement-copy span {
  min-width: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.announcement-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: currentColor;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  transition: opacity 160ms;
}

.announcement-action:hover { opacity: .72; }

@media (max-width: 720px) {
  .announcement-stack { padding: 0 16px; }
  .announcement-banner { grid-template-columns: auto minmax(0, 1fr); align-items: start; }
  .announcement-copy { display: grid; gap: 3px; }
  .announcement-action { grid-column: 2; }
}

@media (prefers-reduced-motion: reduce) {
  .announcement-action { transition: none; }
}
</style>
