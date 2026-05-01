import { reactive } from 'vue'

const THEME_KEY = 'easy-painter:theme'

export const themeState = reactive({
  current: 'light' as 'light' | 'dark',
})

function getSystemPreference(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(theme: 'light' | 'dark') {
  document.documentElement.dataset.theme = theme
}

export function initTheme() {
  const stored = localStorage.getItem(THEME_KEY) as 'light' | 'dark' | null
  themeState.current = stored ?? getSystemPreference()
  applyTheme(themeState.current)

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem(THEME_KEY)) {
      themeState.current = e.matches ? 'dark' : 'light'
      applyTheme(themeState.current)
    }
  })
}

export function toggleTheme() {
  themeState.current = themeState.current === 'light' ? 'dark' : 'light'
  localStorage.setItem(THEME_KEY, themeState.current)
  applyTheme(themeState.current)
}
