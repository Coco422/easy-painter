import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../../deploy/cdn/domain-migration.js', import.meta.url), 'utf8')
function request(path, host = 'legacy.example.invalid', method = 'GET') {
  const response = { headers: {} }
  vm.runInNewContext(source, {
    req: { host, path: path.split('?')[0], uri: path, method },
    resp: { setHeader: (key, value) => { response.headers[key] = value }, send: (status, body) => Object.assign(response, { status, body }) },
  })
  return response
}

test('old pages receive a standalone notice without a login form or application scripts', () => {
  for (const path of ['/', '/login', '/profile', '/gallery/person?from=old']) {
    const result = request(path)
    assert.equal(result.status, 200)
    assert.match(result.body, /旧站域名即将关停/)
    assert.match(result.body, /name="referrer" content="no-referrer"/)
    assert.match(result.headers['Cache-Control'], /no-store/)
    assert.ok(!result.body.includes('<form') && !result.body.includes('/assets/'))
    assert.match(result.headers['Content-Security-Policy'], /default-src 'none'/)
  }
})

test('new domain, API, assets, media and canvas export requests pass through', () => {
  for (const path of ['/api/v1/auth/login', '/api', '/assets/app.js', '/media/image', '/canvas', '/canvas/project', '/login?redirect=%2Fcanvas%2Fproject']) {
    assert.equal(request(path).status, undefined)
  }
  assert.equal(request('/login', 'app.example.invalid').status, undefined)
  assert.equal(request('/login', 'unrelated.example.invalid').status, undefined)
  assert.equal(request('/login', 'legacy.example.invalid', 'POST').status, undefined)
  for (const path of ['/login?redirect=//evil.test', '/login?redirect=%ZZ', '/login?redirect=/profile']) {
    assert.equal(request(path).status, 200)
  }
})

test('countdown navigates after five seconds, preserves the path, and cannot switch destination origin', () => {
  const result = request('/login?invite=ABCD')
  const script = result.body.match(/<script>([\s\S]*?)<\/script>/)[1]
  const elements = { destination: {}, seconds: {}, export: { addEventListener: (_event, callback) => { elements.export.click = callback } } }
  let timeout, interval, destination, timeoutCleared = false, intervalCleared = false
  vm.runInNewContext(script, {
    URL, Date,
    window: { location: { pathname: '//evil.test/path', search: '?invite=ABCD', hash: '#detail', replace: value => { destination = value } } },
    document: { getElementById: id => elements[id] },
    setTimeout: (callback, delay) => { timeout = { callback, delay }; return 1 },
    setInterval: callback => { interval = callback; return 2 },
    clearTimeout: id => { timeoutCleared = id === 1 },
    clearInterval: id => { intervalCleared = id === 2 },
  })
  assert.equal(timeout.delay, 5000)
  interval()
  assert.equal(elements.seconds.textContent, '5')
  timeout.callback()
  assert.equal(destination, 'https://app.example.invalid//evil.test/path?invite=ABCD#detail')
  elements.export.click()
  assert.ok(timeoutCleared && intervalCleared)
})

test('request text is escaped in the HTML fallback', () => {
  const result = request('/login?x="/><script>alert(1)</script>')
  assert.ok(!result.body.includes('<script>alert(1)</script>'))
  assert.match(result.body, /&quot;\/&gt;&lt;script&gt;/)
})
