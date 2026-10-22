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

let panel: HTMLElement | null = null

function renderPanel(scenarios: MockScenarioInfo[], current: string) {
  if (panel) panel.remove()
  panel = document.createElement('div')
  panel.id = 'dev-mock-panel'
  panel.className = 'dev-mock-panel'
  panel.innerHTML = `
    <div class="dev-mock-head">
      <strong>设计预览 · Mock</strong>
      <span>${scenarios.length} 个场景</span>
    </div>
    <div class="dev-mock-list"></div>
    <div class="dev-mock-foot">
      <button type="button" data-action="restart">重放计时</button>
      <button type="button" data-action="exit">退出 mock</button>
    </div>
  `
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
    location.reload()
  })
  document.body.append(panel)
}

export async function bootstrapMock(): Promise<void> {
  if (disabled()) return
  const state = await readState()
  // The middleware is only present in development; a production build never sees it.
  if (!state) return
  await applyState(state, true)
  try {
    const response = await fetch('/__mock/scenarios', { cache: 'no-store' })
    if (response.ok) renderPanel((await response.json()) as MockScenarioInfo[], state.scenario)
  } catch { /* The panel is optional. */ }
}
