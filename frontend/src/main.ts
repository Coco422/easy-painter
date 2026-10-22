import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

// Development only: seeds the mock session and mounts the scenario switcher.
if (import.meta.env.DEV) void import('./lib/dev-mock').then(module => module.bootstrapMock())

createApp(App).use(router).mount('#app')
