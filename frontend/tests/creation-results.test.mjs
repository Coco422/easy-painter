import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as vue from 'vue'
import { compileComponent, compileModule, node, renderer, all, hasClass, textOf } from './helpers/vue-renderer.mjs'
import * as versions from '../src/lib/creation-versions.ts'
import * as media from '../src/lib/media-state.ts'
import * as quipLibrary from '../src/lib/generation-quips.ts'

// Mount the real SFC with Vue's renderer; media is stubbed to avoid private image requests.
const filename = new URL('../src/components/CreationVersions.vue', import.meta.url)
const icon = () => vue.h('svg')
const clock = vue.ref(Date.now())
const mediaClock = { useMediaClock: () => clock }
const modules = {
  vue,
  'lucide-vue-next': { ArrowRight: icon, GitBranch: icon, Layers: icon, Loader2: icon, PencilLine: icon, Plus: icon, Sparkles: icon },
  './ProtectedImage.vue': { __esModule: true, default: { props: ['alt'], setup: props => () => vue.h('img', { alt: props.alt }) } },
  './MediaExpiry.vue': { __esModule: true, default: () => vue.h('span') },
  '@/lib/creation-versions': versions,
  '@/lib/media-state': media,
  '@/composables/useMediaClock': mediaClock, './useMediaClock': mediaClock,
  '@/lib/generation-quips': quipLibrary,
}
modules['@/composables/useGenerationQuips'] = compileModule(fs.readFileSync(new URL('../src/composables/useGenerationQuips.ts', import.meta.url), 'utf8'), modules)
modules['./GenerationWaiting.vue'] = { __esModule: true, default: compileComponent(new URL('../src/components/GenerationWaiting.vue', import.meta.url), modules) }
const Component = compileComponent(filename, modules)
function mount({ parents = {}, selectedId = 'a', ids = ['a', 'b', 'c'], edits = [], overrides = {}, membership = {} } = {}) {
  const jobs = [...ids, ...edits].map((job_id, index) => ({ job_id, created_at: `2026-01-01T00:00:0${index}Z`, prompt: '绘图描述', status: 'succeeded', model: 'm', size: 'auto', credit_cost: 5, billing_status: 'settled', media_state: 'available', image_url: `/image/${job_id}`, ...overrides[job_id] }))
  const props = vue.reactive({ jobs, parents, selectedId, drafting: false, membership: { a: 'one', b: 'one', c: 'two', 'b-edit': 'edit-submission', ...membership }, busy: false, pending: false, editModel: 'm', editCost: 5, editSize: 'auto', maxLength: 4000, canvases: [] })
  const selected = []
  const events = []
  const app = renderer.createApp({ setup: () => () => vue.h(Component, { ...props, onSelect: id => { selected.push(id); props.selectedId = id; props.drafting = false }, onNew: () => { props.drafting = true }, onRetry: job => events.push(['retry', job.job_id]), onDismiss: id => events.push(['dismiss', id]) }) })
  const root = node('root')
  app.mount(root)
  return { root, props, selected, events, app, find: cls => all(root).filter(item => hasClass(item, cls)) }
}

test('results render separate batches of peer candidate cards without version labels before an edit', async () => {
  const view = mount()
  try {
    const batches = view.find('candidate-batch')
    assert.equal(batches.length, 1, 'only the selected batch appears in the workspace')
    assert.equal(view.find('drawing-tab').length, 2, 'other batches remain available in recent drawings')
    assert.deepEqual(batches.map(batch => all(batch).filter(item => hasClass(item, 'candidate-card')).length), [2])
    assert.equal(view.find('version-history').length, 0)
    assert.doesNotMatch(textOf(view.root), /V\d/)
    const second = view.find('candidate-card').find(item => item.props['aria-label'].includes('第 1 批，候选图 2'))
    second.props.onClick()
    await vue.nextTick()
    assert.deepEqual(view.selected, ['b'])
    assert.match(textOf(view.find('version-title')[0]), /第 1 批 · 候选图 2/)
    assert.equal(second.props['aria-pressed'], true)
  } finally { view.app.unmount() }
})

test('each live candidate has a rotating quip, shared with its preview, and finished jobs stop showing it', async () => {
  const ids = ['a', 'b', 'c', 'd']
  const view = mount({ ids, membership: { c: 'one', d: 'one' }, overrides: Object.fromEntries(ids.map(id => [id, { status: 'queued', billing_status: 'reserved' }])) })
  try {
    const cards = view.find('candidate-card')
    const cardLines = cards.map(card => all(card).find(item => hasClass(item, 'waiting-quip')))
    assert.equal(cardLines.length, 4)
    assert.ok(cardLines.every(line => quipLibrary.GENERATION_QUIPS.includes(textOf(line))))
    const preview = () => all(view.find('version-preview')[0]).find(item => hasClass(item, 'waiting-quip'))
    assert.equal(textOf(cardLines[0]), textOf(preview()), 'one job uses the same line in both views')
    assert.match(textOf(view.find('version-preview')[0]), /无需重复提交/)
    const firstNode = preview()
    view.props.jobs[0].status = 'processing'
    await vue.nextTick()
    assert.equal(preview(), firstNode)
    assert.equal(textOf(preview()), textOf(cardLines[0]), 'queue transitions cannot restart the phrase')
    clock.value += 9000
    await vue.nextTick()
    assert.notEqual(preview(), firstNode, 'each phrase enters as a new node to replay its CSS animation')
    assert.notEqual(textOf(preview()), textOf(firstNode))
    assert.equal(view.find('waiting-quip-slot')[0].props['aria-live'], 'off', 'fun lines must not repeatedly interrupt screen readers')
    view.props.jobs.forEach(job => { job.status = 'succeeded'; job.billing_status = 'settled' })
    await vue.nextTick()
    assert.equal(view.find('generation-waiting').length, 0)
    assert.equal(view.find('batch-progress')[0].props['aria-valuenow'], 4)
  } finally { view.app.unmount() }
})

test('selecting an edited candidate shows only its version branch and preserves selection events', async () => {
  const view = mount({ parents: { 'b-edit': 'b', 'b-fork': 'b' }, selectedId: 'b-edit', edits: ['b-edit', 'b-fork'] })
  try {
    assert.equal(view.find('candidate-card').length, 2, 'edits cannot become extra candidates or batches')
    const history = view.find('version-history')[0]
    const versionButtons = history.children.filter(item => item.tag === 'button')
    assert.equal(versionButtons.length, 3)
    assert.deepEqual(versionButtons.map(item => item.props['aria-label']), ['V1，原图，已完成', 'V2，基于 V1，已完成', 'V3，基于 V1，已完成'])
    assert.match(textOf(view.find('version-title')[0]), /第 1 批 · 候选图 2 · V2/)
    versionButtons[2].props.onClick()
    await vue.nextTick()
    assert.deepEqual(view.selected, ['b-fork'])
    const peer = view.find('candidate-card').find(item => item.props['aria-label'].includes('第 1 批，候选图 1'))
    peer.props.onClick()
    await vue.nextTick()
    assert.equal(view.find('version-history').length, 0, 'a peer without edits must not inherit another candidate’s branch')
    assert.match(textOf(view.find('version-title')[0]), /第 1 批 · 候选图 1/)
    const anotherBatch = view.find('drawing-tab').find(item => item.props['aria-label'].includes('第 2 次绘图'))
    anotherBatch.props.onClick()
    await vue.nextTick()
    assert.equal(view.find('version-title').length, 0)
    assert.equal(all(view.find('version-preview')[0]).find(item => item.tag === 'img').props.alt, '生成结果')
    assert.equal(view.find('version-history').length, 0)
    assert.equal(view.find('candidate-card').length, 0)
  } finally { view.app.unmount() }
})

test('a single image is displayed once as a result without candidates or versions', () => {
  const view = mount({ ids: ['a'] })
  try {
    assert.equal(view.find('candidate-card').length, 0)
    assert.equal(view.find('version-history').length, 0)
    assert.equal(view.find('version-title').length, 0)
    assert.equal(all(view.root).filter(item => item.tag === 'img').length, 1)
    assert.match(textOf(view.find('batch-overview')[0]), /单张作品/)
    assert.doesNotMatch(textOf(view.root), /候选|V\d|修改分支/)
    assert.equal(view.find('drawing-tab')[0].props['aria-label'], '查看第 1 次绘图，1 张图片')
  } finally { view.app.unmount() }
})

test('single-image waiting shows one animated quip with the submission reminder and no candidate layer', () => {
  const view = mount({ ids: ['a'], overrides: { a: { status: 'processing', billing_status: 'reserved' } } })
  try {
    assert.equal(view.find('generation-waiting').length, 1)
    assert.equal(view.find('candidate-card').length, 0)
    assert.equal(view.find('version-history').length, 0)
    assert.match(textOf(view.find('waiting-status')[0]), /生成中/)
    assert.ok(quipLibrary.GENERATION_QUIPS.includes(textOf(view.find('waiting-quip')[0])))
    assert.match(textOf(view.find('waiting-note')[0]), /无需重复提交/)
    assert.equal(view.find('batch-progress')[0].props['aria-valuenow'], 0, 'playful text cannot advance real generation progress')
  } finally { view.app.unmount() }
})

test('editing a single image reveals its modification history without introducing candidates', async () => {
  const view = mount({ ids: ['a'], edits: ['a-edit'], parents: { 'a-edit': 'a' }, selectedId: 'a-edit' })
  try {
    assert.equal(view.find('candidate-card').length, 0)
    assert.equal(view.find('drawing-tab').length, 1)
    assert.equal(view.find('version-history').length, 1)
    assert.match(textOf(view.find('version-title')[0]), /V2/)
    assert.match(textOf(view.find('version-history-heading')[0]), /修改记录/)
    assert.doesNotMatch(textOf(view.root), /候选/)
    const original = all(view.find('version-history')[0]).find(item => item.tag === 'button')
    original.props.onClick()
    await vue.nextTick()
    assert.match(textOf(view.find('version-title')[0]), /原图 · V1/)
  } finally { view.app.unmount() }
})

test('progress and billing appear once above candidates and exclude unrelated batches', () => {
  const view = mount({ overrides: { b: { status: 'processing', billing_status: 'reserved' }, c: { status: 'failed', billing_status: 'refunded' } } })
  try {
    const progress = all(view.root).filter(item => item.props.role === 'progressbar')
    assert.equal(progress.length, 1)
    assert.equal(progress[0].props['aria-valuemax'], 2)
    assert.equal(progress[0].props['aria-valuenow'], 1)
    assert.ok(all(view.root).indexOf(progress[0]) < all(view.root).indexOf(view.find('candidate-grid')[0]))
    const overview = textOf(view.find('batch-overview')[0])
    assert.match(overview, /已生成 1 \/ 2 张/)
    assert.match(overview, /已预扣 5 丝/)
    assert.match(overview, /已结算 5 丝/)
    assert.doesNotMatch(overview, /已退回|任务详情与计费/)
    assert.equal(view.find('current-job').length, 0)
  } finally { view.app.unmount() }
})

test('failed results retain refund details and retry/dismiss actions in the selected result', () => {
  const view = mount({ selectedId: 'b', overrides: { b: { status: 'failed', billing_status: 'refunded', error_message: '上游超时' } } })
  try {
    assert.match(textOf(view.find('batch-billing')[0]), /已退回 5 丝/)
    assert.equal(view.find('batch-progress')[0].props['aria-valuenow'], 2)
    const failure = view.find('version-failure')[0]
    assert.match(textOf(failure), /上游超时.*5 丝已全额退回余额/)
    const buttons = all(failure).filter(item => item.tag === 'button')
    buttons[0].props.onClick()
    buttons[1].props.onClick()
    assert.deepEqual(view.events, [['retry', 'b'], ['dismiss', 'b']])
  } finally { view.app.unmount() }
})

test('a running edit contributes to its original batch progress and not a new drawing tab', () => {
  const view = mount({ parents: { 'b-edit': 'b' }, selectedId: 'b-edit', edits: ['b-edit'], overrides: { 'b-edit': { status: 'queued', billing_status: 'reserved' } } })
  try {
    assert.equal(view.find('drawing-tab').length, 2)
    assert.equal(view.find('batch-progress')[0].props['aria-valuemax'], 3)
    assert.equal(view.find('batch-progress')[0].props['aria-valuenow'], 2)
    assert.match(textOf(view.find('batch-overview')[0]), /1 次修改.*1 张生成中/)
  } finally { view.app.unmount() }
})

test('new drawing preserves recent batches and returning does not reopen the previous edit form', async () => {
  const view = mount()
  try {
    const edit = view.find('version-actions')[0].children.find(item => item.tag === 'button')
    edit.props.onClick()
    await vue.nextTick()
    assert.equal(view.find('version-editor').length, 1)
    const jobs = [...view.props.jobs]
    view.find('drawing-next')[0].children.find(item => item.tag === 'button').props.onClick()
    await vue.nextTick()
    assert.equal(view.find('candidate-card').length, 0)
    assert.equal(view.find('version-editor').length, 0)
    assert.equal(view.find('drawing-tab').length, 3)
    assert.deepEqual(view.props.jobs, jobs, 'starting a drawing cannot delete or cancel existing jobs')
    view.find('drawing-tab').find(item => item.props['aria-label']?.includes('第 1 批')).props.onClick()
    await vue.nextTick()
    assert.equal(view.find('candidate-card').length, 2)
    assert.equal(view.find('version-editor').length, 0)
  } finally { view.app.unmount() }
})
