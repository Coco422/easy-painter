import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as vue from 'vue'
import { compileModule, compileComponent, renderer, node, all, hasClass, textOf } from './helpers/vue-renderer.mjs'

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); await vue.nextTick() }
const endpoint = 'https://painter.example.com/api/mcp'
const agent = compileModule(fs.readFileSync(new URL('../src/lib/agent.ts', import.meta.url), 'utf8'), {
  './auth': {}, './browser-crypto': {},
})

function mount({ count = 24, intercept } = {}) {
  const authState = vue.reactive({ sessionId: 'session' })
  const records = Array.from({ length: count + 12 }, (_, i) => ({
    id: `${String(i).padStart(8, '0')}-connection`, label: 'Codex', active: i < count,
    scopes: ['account:read'], max_per_job: 10, created_at: `2026-11-26T01:${String(i).padStart(2, '0')}:00Z`, expires_at: '2026-12-26T01:00:00Z',
  }))
  const calls = []
  const api = async (path, init) => {
    calls.push({ path, method: init?.method ?? 'GET' })
    if (path === '/config') return { enabled: true, endpoint, scopes: {} }
    if (init?.method === 'DELETE') { records.find(row => path.endsWith(row.id)).active = false; return }
    const query = new URL(path, 'https://test').searchParams
    if (intercept) {
      const result = intercept(query)
      if (result) return result
    }
    const state = query.get('state'), size = Number(query.get('page_size'))
    const matching = records.filter(row => state === 'all' || row.active === (state === 'active'))
    const page = Math.min(Number(query.get('page')), Math.max(1, Math.ceil(matching.length / size)))
    return { items: matching.slice((page - 1) * size, page * size).map(row => ({ ...row })), total: matching.length, page, page_size: size }
  }
  const Page = compileComponent(new URL('../src/pages/AgentConnectPage.vue', import.meta.url), {
    vue, 'lucide-vue-next': new Proxy({}, { get: () => () => vue.h('svg') }), './agent.css': {},
    '@/lib/auth': { authState, isLoggedIn: () => !!authState.sessionId },
    '@/lib/agent': { ...agent, agentApi: api },
  }, { URLSearchParams })
  const app = renderer.createApp(Page)
  app.component('router-link', { setup: (_, { slots }) => () => vue.h('a', null, slots.default?.()) })
  const root = node('root')
  app.mount(root)
  const find = cls => all(root).filter(item => hasClass(item, cls))
  const button = label => all(root).find(item => item.tag === 'button' && textOf(item) === label)
  const click = async label => { assert.ok(button(label), label); button(label).props.onClick(); await flush() }
  return { app, root, find, button, click, calls, authState }
}

test('Codex installation uses one add command and the published install block matches it', () => {
  const command = agent.installation('codex', endpoint).text
  assert.equal(command, `codex mcp add easy-painter --url '${endpoint}' --oauth-client-registration dcr`)
  const install = fs.readFileSync(new URL('../../backend/app/agent_content/install.md', import.meta.url), 'utf8')
  assert.equal(install.match(/## Codex CLI\n\n```bash\n([^`]+)```/)[1].trim().replace('{{MCP_URL}}', endpoint), command)
})

test('connections request ten active rows by default and use server pages and filters', async () => {
  const view = mount()
  try {
    await flush()
    assert.equal(view.find('agent-connection').length, 10)
    assert.equal(view.calls[1].path, '/connections?page=1&page_size=10&state=active')
    assert.equal(view.button('上一页').props.disabled, true)
    assert.match(textOf(view.root), /共 24 条连接，每页 10 条/)
    await view.click('下一页')
    assert.match(textOf(view.root), /第 2 \/ 3 页/)
    assert.equal(all(view.find('agent-connection')[0]).find(item => item.props.title)?.props.title, '00000010-connection')
    await view.click('下一页')
    assert.equal(view.find('agent-connection').length, 4)
    assert.equal(view.button('下一页').props.disabled, true)
    await view.click('已失效')
    assert.equal(view.calls.at(-1).path, '/connections?page=1&page_size=10&state=inactive')
    assert.match(textOf(view.root), /共 12 条连接/)
    assert.equal(view.button('调整额度'), undefined)
    await view.click('全部')
    assert.match(textOf(view.root), /共 36 条连接/)
    assert.equal(view.calls.filter(call => call.path === '/config').length, 1, 'paging must not repeatedly load configuration')
  } finally { view.app.unmount() }
})

test('revoking the final item on the final active page returns to the remaining page', async () => {
  const view = mount({ count: 11 })
  try {
    await flush()
    await view.click('下一页')
    assert.equal(view.find('agent-connection').length, 1)
    await view.click('断开')
    assert.equal(view.calls.filter(call => call.method === 'DELETE').length, 0)
    await view.click('确认断开')
    assert.deepEqual(view.calls.find(call => call.method === 'DELETE'), { path: '/connections/00000010-connection', method: 'DELETE' })
    assert.equal(view.find('agent-connection').length, 10)
    assert.match(textOf(view.root), /共 10 条连接/)
    assert.equal(view.button('下一页'), undefined)
  } finally { view.app.unmount() }
})

test('a slower previous page cannot overwrite a newer status filter', async () => {
  let resolvePage
  const view = mount({ intercept: query => query.get('page') === '2' && query.get('state') === 'active'
    ? new Promise(resolve => { resolvePage = resolve }) : undefined })
  try {
    await flush()
    await view.click('下一页')
    assert.equal(view.find('agent-connection').length, 0, 'stale rows are hidden during loading')
    await view.click('已失效')
    resolvePage({ items: [], total: 24, page: 2, page_size: 10 })
    await flush()
    assert.match(textOf(view.root), /共 12 条连接/)
    assert.equal(view.find('agent-connection').length, 10)
    assert.equal(view.button('已失效').props['aria-pressed'], true)
  } finally { view.app.unmount() }
})

test('list errors hide old results and retain a retry without claiming the list is empty', async () => {
  let fail = false
  const view = mount({ intercept: () => fail ? Promise.reject(new Error('network error')) : undefined })
  try {
    await flush()
    fail = true
    await view.click('下一页')
    assert.equal(view.find('agent-connection').length, 0)
    assert.match(textOf(view.root), /加载失败，请点击刷新重试/)
    assert.doesNotMatch(textOf(view.root), /暂无有效连接/)
    fail = false
    await view.click('刷新')
    assert.equal(view.find('agent-connection').length, 10)
  } finally { view.app.unmount() }
})
