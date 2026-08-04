/// <reference types="vite/client" />

declare const __APP_VERSION__: string
declare const __APP_RELEASES__: import('@/lib/release').ReleaseInfo[]

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}
