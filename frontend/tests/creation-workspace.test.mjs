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
function setup({ storage = new Map(), storageFailure = false, create, upload, sourceOverride = {} } = {}) {
  const authState = { user: { id: 'owner' }, sessionId: 'session' }
  const source = { job_id: 'source', status: 'succeeded', prompt: '原始描述', model: 'm', size: 'auto', created_at: '2026-01-01', image_url: '/files/source', media_state: 'available', media_expires_at: null, ...sourceOverride }
  const calls = { posts: [], uploads: 0, images: [], registered: [] }, watchers = []
  const api = {
    ApiError, fetchJob: async () => source,
    uploadReferenceImage: async file => { calls.uploads++; return upload ? upload(file) : { id: 'ref-source' } },
    createJob: async (request, key) => { calls.posts.push(normalize({ request, key })); return create ? create(request, key) : { job_id: 'child', status: 'queued' } },
  }
  const modules = {
    vue: { ref, computed: getter => ({ get value() { return getter() } }), watch: (_, callback) => watchers.push(callback), onBeforeUnmount: () => {} },
    'vue-router': { useRouter: () => ({ push: async () => {} }) },
    '@/lib/api': api,
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
  const options = { jobs: ref([source]), membership: ref({ source: 'batch-one' }), models: ref([{ id: 'm', label: '模型', enabled: true, supports_reference_image: true, max_reference_images: 5, supported_sizes: ['auto'], credit_cost: 5 }]), selectedModel: ref('m'), selectedSize: ref('auto'), maxLength: ref(4000), feedback: ref(''), register: result => calls.registered.push(result), restore: () => {} }
  const app = context.exports.useCreationVersions(options)
  app.selectedId.value = 'source'
  app.history.value.parents.source = null
  return { app, options, source, calls, storage, authState, watchers }
}

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
