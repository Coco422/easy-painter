import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'
import * as versions from '../src/lib/creation-versions.ts'
import * as media from '../src/lib/media-state.ts'

// Mount the real SFC with Vue's renderer; media is stubbed to avoid private image requests.
const filename = new URL('../src/components/CreationVersions.vue', import.meta.url)
const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename: filename.pathname })
const script = compileScript(descriptor, { id: 'creation-results-test', inlineTemplate: true })
const compiled = ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const icon = () => vue.h('svg')
const modules = {
  vue,
  'lucide-vue-next': { ArrowRight: icon, GitBranch: icon, Layers: icon, Loader2: icon, PencilLine: icon, Sparkles: icon },
  './ProtectedImage.vue': { __esModule: true, default: { props: ['alt'], setup: props => () => vue.h('img', { alt: props.alt }) } },
  './MediaExpiry.vue': { __esModule: true, default: () => vue.h('span') },
  '@/lib/creation-versions': versions,
  '@/lib/media-state': media,
  '@/composables/useMediaClock': { useMediaClock: () => vue.ref(Date.now()) },
}
const context = { exports: {}, require: name => { assert.ok(modules[name], name); return modules[name] } }
vm.runInNewContext(compiled, context)
const Component = context.exports.default

function node(tag = '', text = '') {
  return { tag, text, props: {}, children: [], parent: null, listeners: {},
    addEventListener(event, handler) { this.listeners[event] = handler },
    get options() { return this.children.filter(child => child.tag === 'option') },
  }
}
const renderer = vue.createRenderer({
  createElement: tag => node(tag), createText: text => node('', text), createComment: () => node(),
  setText: (item, text) => { item.text = text },
  setElementText: (item, text) => { item.children = []; item.text = text },
  patchProp: (item, key, _, value) => { item.props[key] = value },
  insert(item, parent, anchor = null) {
    if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, item)
    item.parent = parent
  },
  remove(item) { if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1) },
  parentNode: item => item.parent,
  nextSibling: item => item.parent?.children[item.parent.children.indexOf(item) + 1] ?? null,
})
const all = root => [root, ...root.children.flatMap(all)]
const hasClass = (item, name) => String(item.props.class ?? '').split(' ').includes(name)
const textOf = item => item.text + item.children.map(textOf).join('')
function mount({ parents = {}, selectedId = 'a', edits = [] } = {}) {
  const jobs = ['a', 'b', 'c', ...edits].map((job_id, index) => ({ job_id, created_at: `2026-01-01T00:00:0${index}Z`, status: 'succeeded', model: 'm', size: 'auto', media_state: 'available', image_url: `/image/${job_id}` }))
  const props = vue.reactive({ jobs, parents, selectedId, membership: { a: 'one', b: 'one', c: 'two', 'b-edit': 'edit-submission' }, busy: false, pending: false, editModel: 'm', editCost: 5, editSize: 'auto', maxLength: 4000, canvases: [] })
  const selected = []
  const app = renderer.createApp({ setup: () => () => vue.h(Component, { ...props, onSelect: id => { selected.push(id); props.selectedId = id } }) })
  const root = node('root')
  app.mount(root)
  return { root, props, selected, app, find: cls => all(root).filter(item => hasClass(item, cls)) }
}

test('results render separate batches of peer candidate cards without version labels before an edit', async () => {
  const view = mount()
  try {
    const batches = view.find('candidate-batch')
    assert.equal(batches.length, 2)
    assert.deepEqual(batches.map(batch => all(batch).filter(item => hasClass(item, 'candidate-card')).length), [1, 2])
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

test('selecting an edited candidate shows only its version branch and preserves selection events', async () => {
  const view = mount({ parents: { 'b-edit': 'b', 'b-fork': 'b' }, selectedId: 'b-edit', edits: ['b-edit', 'b-fork'] })
  try {
    assert.equal(view.find('candidate-card').length, 3, 'edits cannot become extra candidates or batches')
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
    const anotherBatch = view.find('candidate-card').find(item => item.props['aria-label'].includes('第 2 批'))
    anotherBatch.props.onClick()
    await vue.nextTick()
    assert.match(textOf(view.find('version-title')[0]), /第 2 批 · 候选图 1/)
    assert.equal(view.find('version-history').length, 0)
  } finally { view.app.unmount() }
})
