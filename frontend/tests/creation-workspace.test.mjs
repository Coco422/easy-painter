import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as presets from '../src/lib/creation-presets.ts'
import * as versions from '../src/lib/creation-versions.ts'
import * as media from '../src/lib/media-state.ts'
import * as generationSizes from '../src/lib/generation-sizes.ts'

const compiled = ts.transpileModule(fs.readFileSync(new URL('../src/composables/useCreationVersions.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const ref = value => ({ value })
class ApiError extends Error { constructor(status) { super('API ' + status); this.status = status } }
const normalize = value => JSON.parse(JSON.stringify(value))
function setup({ storage = new Map(), storageFailure = false, create, upload, sourceOverride = {}, historyPage, fetchJob } = {}) {
  const authState = { user: { id: 'owner' }, sessionId: 'session' }
  const source = { job_id: 'source', status: 'succeeded', prompt: '原始描述', model: 'm', size: 'auto', created_at: '2026-01-01', image_url: '/files/source', media_state: 'available', media_expires_at: null, ...sourceOverride }
  const calls = { posts: [], uploads: 0, images: [], registered: [], history: [], details: [], restored: [] }, watchers = []
  const api = {
    ApiError, fetchJob: async id => { calls.details.push(id); return fetchJob ? fetchJob(id) : source },
    uploadReferenceImage: async file => { calls.uploads++; return upload ? upload(file) : { id: 'ref-source' } },
    createJob: async (request, key) => { calls.posts.push(normalize({ request, key })); return create ? create(request, key) : { job_id: 'child', status: 'queued' } },
  }
  const modules = {
    vue: { ref, computed: getter => ({ get value() { return getter() } }), watch: (_, callback) => watchers.push(callback), onBeforeUnmount: () => {} },
    'vue-router': { useRouter: () => ({ push: async () => {} }) },
    '@/lib/api': api,
    '@/lib/artworks': { fetchArtworkPage: async (path, params) => {
      calls.history.push({ path, params: normalize(params) })
      return historyPage ? historyPage(params) : { items: [], total: 0, page: params.page, page_size: 100 }
    } },
    '@/lib/auth': { authState, fetchCurrentUser: async () => {}, fetchImageFile: async url => { calls.images.push(url); return new Response(new Blob(['png'], { type: 'image/png' })) } },
    '@/lib/browser-crypto': { randomId: () => 'stable-key' },
    '@/lib/creation-presets': presets, '@/lib/creation-versions': versions, '@/lib/media-state': media,
    '@/lib/generation-sizes': generationSizes,
    '@/lib/canvas/model': {}, '@/lib/canvas/from-generation': {}, '@/lib/canvas/storage': { listProjects: async () => [] },
  }
  const context = {
    exports: {}, require: name => { assert.ok(modules[name], name); return modules[name] },
    File, Blob, AbortController, location: { origin: 'https://paint.test' },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => { if (storageFailure) throw new Error('quota'); storage.set(key, value) } },
  }
  vm.runInNewContext(compiled, context)
  const options = { jobs: ref([source]), membership: ref({ source: 'batch-one' }), models: ref([{ id: 'm', label: '模型', enabled: true, supports_reference_image: true, max_reference_images: 5, supported_sizes: ['auto'], credit_cost: 5 }]), selectedModel: ref('m'), selectedSize: ref('auto'), maxLength: ref(4000), feedback: ref(''), register: result => calls.registered.push(result), restore: job => calls.restored.push(job) }
  const app = context.exports.useCreationVersions(options)
  app.selectedId.value = 'source'
  app.history.value.parents.source = null
  return { app, options, source, calls, storage, authState, watchers }
}

test('restoring an old local history uses one time-filtered list request and never fetches old job details', async () => {
  const parents = Object.fromEntries(Array.from({ length: 100 }, (_, i) => [`old-${i}`, null]))
  const storage = new Map([[versions.creationHistoryKey('owner'), JSON.stringify({ parents })]])
  const { app, calls } = setup({ storage })
  const before = Date.now()
  await app.load()
  assert.equal(calls.history.length, 1)
  assert.equal(calls.history[0].path, 'history')
  const cutoff = Date.parse(calls.history[0].params.from_date)
  assert.ok(cutoff >= before - 24 * 60 * 60 * 1000 && cutoff <= Date.now() - 24 * 60 * 60 * 1000)
  assert.deepEqual(calls.details, [])
  assert.deepEqual(calls.restored, [])
  assert.equal(Object.keys(app.history.value.parents).length, 100, 'older ancestry is retained without restoring details')
})

test('recent restoration handles pagination and only requests locally retained jobs from the last 24 hours', async () => {
  const recent = new Date(Date.now() - 60_000).toISOString()
  const parents = { first: null, second: 'old', old: null }
  const storage = new Map([[versions.creationHistoryKey('owner'), JSON.stringify({ parents })]])
  const { app, calls } = setup({ storage,
    historyPage: ({ page }) => ({ items: page === 1
      ? [{ id: 'first', created_at: recent }, ...Array.from({ length: 99 }, (_, i) => ({ id: `other-${i}`, created_at: recent }))]
      : [{ id: 'second', created_at: recent }, { id: 'old', created_at: '2000-01-01' }],
      total: 102, page, page_size: 100 }),
    fetchJob: async id => ({ job_id: id, created_at: recent }),
  })
  await app.load()
  assert.equal(calls.history.length, 2)
  assert.equal(calls.history[0].params.from_date, calls.history[1].params.from_date)
  assert.deepEqual(calls.details, ['first', 'second'])
  assert.deepEqual(calls.restored.map(job => job.job_id), ['first', 'second'])
  assert.equal(app.history.value.parents.second, 'old', 'a recent edit retains its older parent relation without loading the parent')
})

test('a failed recent list cannot fall back to requesting every old job and preserves pending confirmation', async () => {
  const pending = { key: 'key', parentId: 'old', request: { prompt: '改蓝色', model: 'm', size: 'auto', reference_image_ids: ['ref'] } }
  const storage = new Map([[versions.creationHistoryKey('owner'), JSON.stringify({ parents: { old: null }, pending })]])
  const { app, calls, options } = setup({ storage, historyPage: async () => { throw new Error('offline') } })
  await app.load()
  assert.deepEqual(calls.details, [])
  assert.deepEqual(calls.posts, [])
  assert.deepEqual(normalize(app.history.value.pending), pending)
  assert.match(options.feedback.value, /最近一天绘图暂时无法恢复/)
})

test('lost revision response survives reload and confirmation reuses exact request/key without another upload', async () => {
  const first = setup({ create: async () => { throw new ApiError(503) } })
  await first.app.revise('改成蓝色')
  assert.ok(first.app.history.value.pending)
  const restored = setup({ storage: first.storage })
  await restored.app.load()
  assert.equal(restored.calls.posts.length, 0, 'loading cannot automatically submit a paid request')
  await restored.app.confirm()
  assert.deepEqual(restored.calls.posts[0], first.calls.posts[0])
  assert.equal(first.calls.uploads, 1)
  assert.equal(restored.calls.uploads, 0)
  assert.equal(restored.app.history.value.parents.child, 'source')
  assert.equal(restored.app.history.value.pending, null)
})

test('storage failure prevents paid submission, including the manual confirmation path', async () => {
  const { app, calls } = setup({ storageFailure: true })
  await app.revise('改成蓝色')
  assert.ok(app.history.value.pending)
  await app.confirm()
  assert.equal(calls.posts.length, 0)
  assert.match(app.storageError.value, /无法保存/)
})

test('retrying a failed edit uses its original parent and exact prompt, retaining the failed version', async () => {
  const { app, calls, options } = setup()
  const failed = { job_id: 'failed', model: 'm', size: 'auto', prompt: '原改图要求', status: 'failed', created_at: '2026-01-02' }
  options.jobs.value.push(failed)
  app.history.value.parents.failed = 'source'
  app.selectedId.value = 'unrelated'
  await app.retryRevision(failed)
  assert.deepEqual(calls.images, ['/files/source'])
  assert.equal(calls.posts[0].request.prompt, failed.prompt)
  assert.deepEqual(calls.posts[0].request.reference_image_ids, ['ref-source'])
  assert.ok(options.jobs.value.includes(failed))
  assert.equal(app.history.value.parents.child, 'source')
})

test('editing a selected parallel candidate references only that image and preserves its peers', async () => {
  const { app, calls, options, source, storage } = setup()
  const candidate = { ...source, job_id: 'candidate-two', image_url: '/files/candidate-two', created_at: '2026-01-02' }
  options.jobs.value.push(candidate)
  options.membership.value[candidate.job_id] = 'batch-one'
  app.record(candidate.job_id)
  app.selectedId.value = candidate.job_id
  await app.revise('改成蓝色')
  assert.deepEqual(calls.images, ['/files/candidate-two'])
  assert.equal(calls.posts.length, 1)
  assert.equal(app.history.value.parents.child, candidate.job_id)
  assert.equal(app.history.value.parents.source, null)
  assert.equal(app.history.value.parents[candidate.job_id], null)
  assert.ok(options.jobs.value.includes(source))
  assert.ok(options.jobs.value.includes(candidate))
  assert.equal(versions.parseCreationHistory(storage.get(versions.creationHistoryKey('owner'))).parents.child, candidate.job_id)
})

test('account switch during reference upload cannot create a job or register results for the next account', async () => {
  let finishUpload, started
  const uploading = new Promise(resolve => { started = resolve })
  const { app, calls, authState, watchers } = setup({ upload: () => { started(); return new Promise(resolve => { finishUpload = resolve }) } })
  const action = app.revise('改成蓝色')
  await uploading
  authState.user = { id: 'another-owner' }
  authState.sessionId = 'another-session'
  watchers[0]()
  finishUpload({ id: 'ref-source' })
  await action
  assert.equal(calls.posts.length, 0)
  assert.equal(calls.registered.length, 0)
  assert.deepEqual(normalize(app.history.value), versions.emptyCreationHistory())
})

test('expired and foreign-origin originals never fetch, upload or create paid edits', async () => {
  for (const sourceOverride of [{ media_expires_at: '2000-01-01' }, { image_url: 'https://foreign.test/image.png' }]) {
    const { app, calls } = setup({ sourceOverride })
    await app.revise('改成蓝色')
    assert.equal(calls.images.length, 0)
    assert.equal(calls.uploads, 0)
    assert.equal(calls.posts.length, 0)
  }
})

test('a definitive billing refusal clears pending confirmation without replacing the selected original', async () => {
  const { app, options } = setup({ create: async () => { throw new ApiError(402) } })
  await app.revise('改成蓝色')
  assert.equal(app.history.value.pending, null)
  assert.equal(app.selectedId.value, 'source')
  assert.equal(options.jobs.value.length, 1)
  assert.match(options.feedback.value, /402/)
})
