import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as vue from 'vue'
import * as presets from '../src/lib/creation-presets.ts'
import * as versions from '../src/lib/creation-versions.ts'
import * as media from '../src/lib/media-state.ts'
import * as batches from '../src/lib/generation-batch.ts'
import * as layout from '../src/lib/image-layout.ts'
import * as generationSizes from '../src/lib/generation-sizes.ts'
import * as pricing from '../src/lib/model-pricing.ts'
import * as quipLibrary from '../src/lib/generation-quips.ts'
import { compileComponent, compileModule, node, renderer, all, hasClass, textOf, teleportTarget } from './helpers/vue-renderer.mjs'

const icon = () => vue.h('svg')
const component = value => ({ __esModule: true, default: value })
const image = component({ props: ['alt'], setup: props => () => vue.h('img', { alt: props.alt }) })
const expiry = component(() => vue.h('span'))
class ApiError extends Error {}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); await vue.nextTick() }

function mount({ live = false, pending = null } = {}) {
  const selectedReferences = vue.ref([{ id: 'old-reference', filename: '旧海报.png' }])
  const uploading = vue.ref(false)
  const calls = { posts: [], confirms: 0, clearedTimers: [] }
  const storage = new Map([['easy-painter:job-batches', JSON.stringify({ a: 'old', b: 'old', c: 'old', d: 'old' })]])
  const localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  let timerId = 0, identifier = 0, finishOld
  const window = { localStorage, matchMedia: () => ({ matches: true }), addEventListener() {}, removeEventListener() {},
    setTimeout: () => ++timerId, clearTimeout: id => calls.clearedTimers.push(id) }
  const oldJobs = ['a', 'b', 'c', 'd'].map((job_id, index) => ({ job_id, status: live && index === 0 ? 'processing' : 'succeeded', prompt: '旧海报', model: 'm', model_label: '模型', size: 'auto', credit_cost: 5, billing_status: live && index === 0 ? 'reserved' : 'settled', created_at: `2026-01-01T00:00:0${index}Z`, image_url: `/image/${job_id}`, media_state: 'available' }))
  const liveResult = new Promise(resolve => { finishOld = () => resolve({ ...oldJobs[0], status: 'succeeded', billing_status: 'settled' }) })
  const model = { id: 'm', label: '模型', enabled: true, credit_cost: 5, base_credit_cost: 5, supports_reference_image: true, max_reference_images: 5, supported_sizes: ['auto', '1280x720'] }
  const created = new Map()
  const api = { ApiError,
    fetchPublicMeta: async () => ({ models: [model, { ...model, id: 'm-alt', label: '另一个模型' }], prompt_max_length: 4000, polling_interval_ms: 1000 }),
    fetchActiveJobs: async () => live ? [oldJobs[0]] : [],
    fetchJob: async id => id === 'a' && live ? liveResult : created.get(id) ?? oldJobs.find(job => job.job_id === id),
    createJob: async (payload, key) => {
      const id = `new-${calls.posts.length + 1}`
      calls.posts.push({ payload: JSON.parse(JSON.stringify(payload)), key })
      created.set(id, { ...oldJobs[0], ...payload, job_id: id, status: 'succeeded', billing_status: 'settled', created_at: `2026-02-01T00:00:0${calls.posts.length}Z` })
      return { job_id: id, status: 'queued', credit_cost: 5, billing_status: 'reserved' }
    },
  }
  let history, retainedJobs
  const useCreationVersions = options => {
    history = vue.ref({ parents: Object.fromEntries(oldJobs.map(job => [job.job_id, null])), pending })
    retainedJobs = options.jobs
    return { history, selectedId: vue.ref('a'), busy: vue.ref(false), storageError: vue.ref(''), canvases: vue.ref([]), editModel: vue.ref(model), editSize: vue.ref('auto'),
      load: async () => { oldJobs.forEach(options.restore) },
      record: id => { history.value.parents[id] ??= null }, forget() {},
      confirm: () => { calls.confirms++ }, revise() {}, retryRevision() {}, addToCanvas() {},
    }
  }
  const modules = {
    vue, 'lucide-vue-next': new Proxy({}, { get: () => icon }),
    'naive-ui': {
      NSelect: {
        props: ['value', 'options', 'disabled'],
        setup(props, { attrs, emit }) {
          return () => vue.h('select', {
            ...attrs,
            value: props.value,
            disabled: props.disabled,
            onChange: event => emit('update:value', event.target.value),
          }, (props.options ?? []).map(option => vue.h('option', {
            key: option.value,
            value: option.value,
            disabled: option.disabled,
          }, option.label)))
        },
      },
    },
    'vue-router': { useRoute: () => ({ query: { prompt: '旧海报' } }), useRouter: () => ({ push() {} }) },
    '@/lib/api': api, '@/lib/auth': { authState: vue.reactive({ user: { id: 'owner', credits: 1000 }, sessionId: 'session' }), fetchCurrentUser: async () => {}, isLoggedIn: () => true },
    '@/lib/browser-crypto': { randomId: () => `key-${++identifier}` },
    '@/lib/creation-presets': presets, '@/lib/generation-batch': batches, '@/lib/image-layout': layout, '@/lib/model-pricing': pricing,
    '@/lib/generation-sizes': generationSizes,
    '@/lib/creation-versions': versions, '@/lib/media-state': media,
    '@/lib/generation-quips': quipLibrary,
    '@/composables/useMediaClock': { useMediaClock: () => vue.ref(Date.now()) },
    '@/composables/useReferenceImages': { useReferenceImages: () => ({ selected: selectedReferences, uploading, getObjectUrl: () => '', releaseObjectUrls() {}, clearSelected: () => { selectedReferences.value = [] }, deselect() {} }) },
    '@/composables/useCreationVersions': { useCreationVersions },
    './ProtectedImage.vue': image, '@/components/ProtectedImage.vue': image, './MediaExpiry.vue': expiry, '@/components/MediaExpiry.vue': expiry,
    '@/components/ReferenceHistoryDrawer.vue': component(() => vue.h('div')),
    '@/components/ArtworkModal.vue': component(() => vue.h('div')), '@/lib/artworks': {},
  }
  const environment = { window, localStorage }
  modules['./useMediaClock'] = modules['@/composables/useMediaClock']
  modules['@/composables/useGenerationQuips'] = compileModule(fs.readFileSync(new URL('../src/composables/useGenerationQuips.ts', import.meta.url), 'utf8'), modules)
  modules['./GenerationWaiting.vue'] = component(compileComponent(new URL('../src/components/GenerationWaiting.vue', import.meta.url), modules, environment))
  modules['@/components/GeneratePanel.vue'] = component(compileComponent(new URL('../src/components/GeneratePanel.vue', import.meta.url), modules, environment))
  modules['@/components/CreationVersions.vue'] = component(compileComponent(new URL('../src/components/CreationVersions.vue', import.meta.url), modules, environment))
  const Page = compileComponent(new URL('../src/pages/CreatePage.vue', import.meta.url), modules, environment)
  const app = renderer.createApp(Page)
  app.component('router-link', { setup: (_, { slots }) => () => vue.h('a', null, slots.default?.()) })
  const root = node('root')
  app.mount(root)
  const find = cls => all(root).filter(item => hasClass(item, cls))
  const choose = async (label, value) => {
    const field = all(root).find(item => hasClass(item, 'pill--select') && textOf(item).startsWith(label))
    const select = all(field).find(item => item.tag === 'select')
    select.options.forEach(option => { option.selected = option.value === value })
    select.value = value
    if (select.listeners.change) select.listeners.change({ target: select })
    else select.props.onChange({ target: select })
    await vue.nextTick()
  }
  const input = value => find('prompt-textarea')[0].props.onInput({ target: { value } })
  return { app, root, calls, storage, selectedReferences, uploading, find, choose, input, finishOld, get history() { return history.value }, get jobs() { return retainedJobs.value } }
}

test('new drawing clears content and all presets, keeps generation parameters and starts an independent batch', async () => {
  const view = mount()
  try {
    await flush()
    assert.equal(view.find('candidate-card').length, 0, 'refresh keeps the workspace on a new drawing')
    assert.equal(view.find('workspace-empty')[0] !== undefined, true)
    assert.equal(all(view.root).some(item => item.tag === 'img' && String(item.props.src ?? '').startsWith('/image/')), false, 'draft state does not fetch historical result images')
    await view.choose('创作用途', 'poster')
    await view.choose('视觉风格', 'photo')
    await view.choose('图中文字', 'en')
    await view.choose('模型', 'm-alt')
    await view.find('size-picker-trigger')[0].props.onClick()
    all(teleportTarget).find(item => hasClass(item, 'size-option-card') && textOf(item).includes('1280 × 720')).props.onClick()
    await vue.nextTick()
    view.find('batch-segmented')[0].children.find(item => item.tag === 'button' && textOf(item).includes('4 张')).props.onClick()
    await vue.nextTick()
    assert.match(textOf(view.find('creation-final-prompt')[0]), /海报.*写实摄影.*英语/s)
    await view.find('results-toolbar-button--primary')[0].props.onClick()
    await flush()
    assert.equal(view.find('prompt-textarea')[0].props.value, '')
    assert.equal(view.find('prompt-textarea')[0].focused, true)
    assert.equal(view.selectedReferences.value.length, 0)
    assert.equal(view.jobs.length, 4)
    assert.equal(view.calls.posts.length, 0, 'starting a draft cannot submit paid requests')
    assert.equal(view.find('candidate-card').length, 0)
    assert.equal(view.find('drawing-tab').length, 2)
    assert.match(textOf(view.find('billing-estimate')[0]), /5 丝 × 4 张 = 20 丝/)
    assert.ok(all(view.root).some(item => item.tag === 'h3' && textOf(item) === '换一个全新的想法'))
    view.input('一座雪山')
    await vue.nextTick()
    assert.match(textOf(view.find('creation-final-prompt')[0]), /一座雪山/)
    assert.doesNotMatch(textOf(view.find('creation-final-prompt')[0]), /海报|写实摄影|英语/)
    view.find('primary-button')[0].props.onClick()
    await flush()
    assert.equal(view.calls.posts.length, 4)
    assert.ok(view.calls.posts.every(({ payload }) => payload.prompt === '一座雪山' && payload.model === 'm-alt' && payload.size === '1280x720' && payload.reference_image_ids.length === 0))
    assert.equal(view.jobs.length, 8)
    const membership = JSON.parse(view.storage.get('easy-painter:job-batches'))
    assert.equal(new Set(['new-1', 'new-2', 'new-3', 'new-4'].map(id => membership[id])).size, 1)
    assert.notEqual(membership['new-1'], membership.a)
    assert.ok(['new-1', 'new-2', 'new-3', 'new-4'].every(id => view.history.parents[id] === null))
    assert.equal(view.find('candidate-card').length, 4)
    assert.equal(view.find('drawing-tab').length, 2)
    assert.ok(!textOf(view.root).includes('任务详情与计费'))
  } finally { view.app.unmount() }
})

test('a previous batch finishing cannot replace the new drawing or clear its new prompt', async () => {
  const view = mount({ live: true })
  try {
    await flush()
    assert.equal(view.find('results-toolbar-button--primary')[0].props.disabled, false)
    await view.find('results-toolbar-button--primary')[0].props.onClick()
    view.input('新的风景')
    view.finishOld()
    await flush()
    assert.equal(view.find('prompt-textarea')[0].props.value, '新的风景')
    assert.equal(view.jobs.find(job => job.job_id === 'a').status, 'succeeded')
    assert.equal(view.find('candidate-card').length, 0)
    assert.match(textOf(view.find('feedback-banner')[0]), /之前的绘图已生成/)
    assert.equal(view.calls.posts.length, 0)
  } finally { view.app.unmount() }
})

test('uploading blocks reset, and a new draft never erases an unknown revision request', async () => {
  const pending = { key: 'unknown-key', parentId: 'a', request: { prompt: '旧改图', model: 'm', size: 'auto', reference_image_ids: ['old-reference'] } }
  const view = mount({ pending })
  try {
    await flush()
    view.uploading.value = true
    await vue.nextTick()
    assert.equal(view.find('results-toolbar-button--primary')[0].props.disabled, true)
    await view.find('results-toolbar-button--primary')[0].props.onClick()
    assert.equal(view.find('prompt-textarea')[0].props.value, '旧海报')
    assert.equal(view.selectedReferences.value.length, 1)
    view.uploading.value = false
    await vue.nextTick()
    await view.find('results-toolbar-button--primary')[0].props.onClick()
    await flush()
    assert.deepEqual(JSON.parse(JSON.stringify(view.history.pending)), pending)
    assert.match(textOf(view.root), /确认上次改图任务/)
    assert.equal(view.calls.confirms, 0)
    assert.equal(view.calls.posts.length, 0)
  } finally { view.app.unmount() }
})
