// Development-only helper. Seeds a fake session and renders a scenario switcher.
// The corresponding API answers come from mock/plugin.ts (Vite middleware).
const DISABLED_KEY = 'easy-painter:dev-mock-disabled'
const SEEDED_KEY = 'easy-painter:dev-mock-seeded'
const RELOADED_KEY = 'easy-painter:dev-mock-reloaded-fingerprint'
const TOKEN_KEY = 'easy-painter:token'

interface MockState {
  scenario: string
  token: string
  user: { id: string; display_name: string }
  storage: Record<string, string>
}

interface MockScenarioInfo {
  name: string
  label: string
  detail: string
}

function disabled(): boolean {
  if (new URLSearchParams(location.search).get('mock') === 'off') return true
  return localStorage.getItem(DISABLED_KEY) === '1'
}

async function readState(): Promise<MockState | null> {
  try {
    const response = await fetch('/__mock/state', { cache: 'no-store' })
    if (!response.ok) return null
    return (await response.json()) as MockState
  } catch { return null }
}

/** Keeps a stable fake identity per tab so polling and session checks behave. */
async function applyState(state: MockState, reload: boolean): Promise<boolean> {
  const fingerprint = `${state.scenario}:${state.token}`
  const seeded = sessionStorage.getItem(SEEDED_KEY)
  const ownToken = state.token.split('.')[1]
  localStorage.setItem(TOKEN_KEY, state.token)
  for (const [key, value] of Object.entries(state.storage)) localStorage.setItem(key, value)
  sessionStorage.setItem(SEEDED_KEY, fingerprint)
  if (!reload || !ownToken || seeded === fingerprint) return false
  // A time-based brake, not a fingerprint check: any drift in the mock's state
  // must never be able to reload the page faster than twice a second.
  const lastReload = Number(sessionStorage.getItem(RELOADED_KEY) ?? '0')
  if (Date.now() - lastReload < 2000) return false
  sessionStorage.setItem(RELOADED_KEY, String(Date.now()))
  location.reload()
  return true
}

// Kept out of the production stylesheet: only injected when the mock boots.
const PANEL_CSS = `.dev-mock-panel {
  position: fixed; left: 16px; bottom: 16px; z-index: 90;
  width: 264px; max-height: min(70vh, 620px); overflow: auto;
  padding: 10px; border: 1px solid var(--border); border-radius: 12px;
  background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
  box-shadow: var(--shadow-lg); backdrop-filter: blur(12px);
  font-family: var(--font-body); font-size: 12px; color: var(--text-primary);
}
.dev-mock-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 2px 4px 8px; cursor: grab; touch-action: none; user-select: none; }
.dev-mock-head:active { cursor: grabbing; }
.dev-mock-collapse {
  flex: none; width: 22px; height: 22px; min-height: 0; padding: 0;
  border: 1px solid var(--border); border-radius: 5px; background: transparent;
  color: var(--text-secondary); font-size: 10px; line-height: 1; cursor: pointer;
}
.dev-mock-collapse:hover { border-color: var(--border-accent); color: var(--accent-strong); }
.dev-mock-panel.is-collapsed { width: auto; max-width: 220px; padding: 6px 8px; }
.dev-mock-panel.is-collapsed .dev-mock-head { padding-bottom: 0; }
.dev-mock-panel.is-collapsed .dev-mock-list,
.dev-mock-panel.is-collapsed .dev-mock-foot { display: none; }
.dev-mock-head strong { font-size: 12px; font-weight: 600; color: var(--accent-strong); }
.dev-mock-head span { font-size: 10.5px; color: var(--text-muted); }
.dev-mock-list { display: grid; gap: 3px; }
.dev-mock-item {
  display: grid; gap: 2px; width: 100%; padding: 7px 8px; text-align: left;
  border: 1px solid transparent; border-radius: 7px; background: transparent;
  color: var(--text-primary); font: inherit; cursor: pointer;
}
.dev-mock-item:hover { background: var(--bg-hover); }
.dev-mock-item[aria-pressed='true'] { border-color: var(--border-accent); background: var(--accent-soft); }
.dev-mock-item > span { font-size: 12px; }
.dev-mock-item small { font-size: 10.5px; line-height: 1.5; color: var(--text-muted); }
.dev-mock-foot { display: flex; gap: 6px; margin-top: 6px; padding-top: 8px; border-top: 1px solid var(--border); }
.dev-mock-foot button {
  flex: 1; min-height: 28px; border: 1px solid var(--border); border-radius: 6px;
  background: transparent; color: var(--text-secondary); font: inherit; font-size: 11px; cursor: pointer;
}
.dev-mock-foot button:hover { border-color: var(--border-accent); color: var(--accent-strong); }`

function injectPanelStyles() {
  if (document.getElementById('dev-mock-styles')) return
  const style = document.createElement('style')
  style.id = 'dev-mock-styles'
  style.textContent = PANEL_CSS
  document.head.append(style)
}

let panel: HTMLElement | null = null

const COLLAPSED_KEY = 'easy-painter:dev-mock-collapsed'
const POSITION_KEY = 'easy-painter:dev-mock-position'

function renderPanel(scenarios: MockScenarioInfo[], current: string) {
  if (panel) panel.remove()
  panel = document.createElement('div')
  panel.id = 'dev-mock-panel'
  panel.className = 'dev-mock-panel'
  if (localStorage.getItem(COLLAPSED_KEY) === '1') panel.classList.add('is-collapsed')
  const saved = localStorage.getItem(POSITION_KEY)
  if (saved) {
    try {
      const { left, top } = JSON.parse(saved) as { left: number; top: number }
      if (Number.isFinite(left) && Number.isFinite(top)) {
        panel.style.left = `${Math.max(0, Math.min(left, innerWidth - 80))}px`
        panel.style.top = `${Math.max(0, Math.min(top, innerHeight - 44))}px`
        panel.style.bottom = 'auto'
      }
    } catch { /* A corrupt position just falls back to the corner. */ }
  }
  panel.innerHTML = `
    <div class="dev-mock-head">
      <strong>设计预览 · Mock</strong>
      <span>${scenarios.length} 个场景</span>
      <button type="button" class="dev-mock-collapse" data-action="collapse" aria-label="收起或展开场景面板"></button>
    </div>
    <div class="dev-mock-list"></div>
    <div class="dev-mock-foot">
      <button type="button" data-action="restart">重放计时</button>
      <button type="button" data-action="exit">退出 mock</button>
    </div>
  `
  const collapse = panel.querySelector('[data-action="collapse"]') as HTMLElement
  const syncCollapse = () => {
    const collapsed = panel!.classList.contains('is-collapsed')
    collapse.textContent = collapsed ? '▸' : '▾'
    collapse.title = collapsed ? '展开场景列表' : '收起场景列表'
  }
  syncCollapse()
  collapse.addEventListener('click', () => {
    const collapsed = panel!.classList.toggle('is-collapsed')
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0')
    syncCollapse()
  })
  // Drag by the header; the inner buttons keep their own clicks.
  const head = panel.querySelector('.dev-mock-head') as HTMLElement
  head.addEventListener('pointerdown', (event: PointerEvent) => {
    if (event.target instanceof Element && event.target.closest('button')) return
    const box = panel!.getBoundingClientRect()
    const offsetX = event.clientX - box.left
    const offsetY = event.clientY - box.top
    head.setPointerCapture(event.pointerId)
    const move = (moveEvent: PointerEvent) => {
      panel!.style.left = `${Math.max(0, Math.min(moveEvent.clientX - offsetX, innerWidth - 60))}px`
      panel!.style.top = `${Math.max(0, Math.min(moveEvent.clientY - offsetY, innerHeight - 40))}px`
      panel!.style.bottom = 'auto'
    }
    const up = () => {
      head.removeEventListener('pointermove', move)
      head.removeEventListener('pointerup', up)
      localStorage.setItem(POSITION_KEY, JSON.stringify({
        left: Number.parseInt(panel!.style.left, 10) || 0,
        top: Number.parseInt(panel!.style.top, 10) || 0,
      }))
    }
    head.addEventListener('pointermove', move)
    head.addEventListener('pointerup', up)
  })
  const list = panel.querySelector('.dev-mock-list') as HTMLElement
  for (const scenario of scenarios) {
    const item = document.createElement('button')
    item.type = 'button'
    item.className = 'dev-mock-item'
    item.setAttribute('aria-pressed', String(scenario.name === current))
    item.innerHTML = `<span>${scenario.label}</span><small>${scenario.detail}</small>`
    item.addEventListener('click', () => {
      void fetch(`/__mock/select?name=${encodeURIComponent(scenario.name)}`, { cache: 'no-store' })
        .then(async () => {
          sessionStorage.removeItem(SEEDED_KEY)
          sessionStorage.removeItem(RELOADED_KEY)
          const state = await readState()
          // A deliberate switch always lands on the new scenario, even if the
          // brake declined to reload above.
          if (!state || !(await applyState(state, true))) location.reload()
        })
    })
    list.append(item)
  }
  panel.querySelector('[data-action="restart"]')?.addEventListener('click', () => {
    void fetch('/__mock/restart', { cache: 'no-store' }).then(() => location.reload())
  })
  panel.querySelector('[data-action="exit"]')?.addEventListener('click', () => {
    localStorage.setItem(DISABLED_KEY, '1')
    localStorage.removeItem(TOKEN_KEY)
    void fetch('/__mock/disable', { cache: 'no-store' }).finally(() => location.reload())
  })
  document.body.append(panel)
}

export async function bootstrapMock(): Promise<void> {
  if (disabled()) {
    await fetch('/__mock/disable', { cache: 'no-store' }).catch(() => undefined)
    return
  }
  const state = await readState()
  // The middleware is only present in development; a production build never sees it.
  if (!state) return
  await applyState(state, true)
  injectPanelStyles()
  try {
    const response = await fetch('/__mock/scenarios', { cache: 'no-store' })
    if (response.ok) renderPanel((await response.json()) as MockScenarioInfo[], state.scenario)
  } catch { /* The panel is optional. */ }
}
