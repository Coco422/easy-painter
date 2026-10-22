import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

// Initialize the development mock before app requests start so its session
// cookie is ready before the first API call. A disabled mock opts into Vite's
// regular API proxy.
async function startApp() {
  if (import.meta.env.DEV) await import('./lib/dev-mock').then(module => module.bootstrapMock())
  createApp(App).use(router).mount('#app')
}

void startApp()
