import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/lib/auth.ts', import.meta.url), 'utf8')
  .replace("import { reactive } from 'vue'", 'const reactive = value => value')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const key = 'easy-painter:token'
function token({ sub = 'user-1', sid = 'session-1', exp = Date.now() / 1000 + 900, ...rest } = {}) {
  return `header.${Buffer.from(JSON.stringify({ sub, sid, exp, typ: sid ? 'access' : undefined, ...rest })).toString('base64url')}.signature`
}
function json(data, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function setup({ initial = token(), fetch, hidden = false, locks } = {}) {
  const storage = new Map(initial ? [[key, initial]] : [])
  const listeners = {}
  const context = {
    exports: {}, Headers, URL, Response, DOMException, atob,
    navigator: locks ? { locks } : {},
    document: { visibilityState: hidden ? 'hidden' : 'visible' },
    window: { location: { origin: 'https://paint.test' }, addEventListener: (type, fn) => { listeners[type] = fn } },
    localStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, value) => storage.set(k, value), removeItem: k => storage.delete(k) },
    fetch,
  }
  vm.runInNewContext(compiled, context)
  return { ...context.exports, context, storage, listeners }
}

test('403 / 429 / 503 and HTML 401 retain token and loaded profile', async () => {
  for (const status of [403, 429, 503, 401]) {
    const app = setup({ fetch: async () => status === 401 ? new Response('challenge', { status }) : json({}, status) })
    const previous = { id: 'user-1', display_name: 'Loaded user' }
    app.authState.user = previous
    await app.fetchCurrentUser()
    assert.ok(app.authState.token)
    assert.equal(app.authState.user, previous)
    assert.equal(app.storage.get(key), app.authState.token)
  }
})

test('expired token refreshes once for concurrent requests and preserves stable session identity', async () => {
  const initial = token({ exp: Date.now() / 1000 - 60 })
  const fresh = token()
  let refreshes = 0
  const app = setup({ initial, fetch: async (url, init) => {
    if (url.endsWith('/auth/refresh')) { refreshes++; await new Promise(r => setTimeout(r, 5)); return json({ access_token: fresh }) }
    assert.equal(init.headers.get('Authorization'), `Bearer ${fresh}`)
    return json({ id: 'user-1' })
  } })
  app.authState.user = { id: 'user-1' }
  const identity = app.authState.sessionId
  await Promise.all([app.authenticatedFetch('/api/v1/jobs/1'), app.fetchCurrentUser(), app.authenticatedFetch('/api/v1/media/file')])
  assert.equal(refreshes, 1)
  assert.equal(app.authState.sessionId, identity)
  assert.equal(app.authState.user.id, 'user-1')
})

test('application 401 refreshes and retries a paid POST only once with identical body and idempotency key', async () => {
  const calls = []
  const app = setup({ fetch: async (url, init) => {
    calls.push({ url, init })
    if (url.endsWith('/refresh')) return json({ access_token: token({ exp: Date.now() / 1000 + 1000 }) })
    return json({ detail: 'expired' }, 401)
  } })
  const body = JSON.stringify({ prompt: 'a tree' })
  const response = await app.authenticatedFetch('/api/v1/jobs', { method: 'POST', body, headers: { 'Idempotency-Key': 'stable' } })
  assert.equal(response.status, 401)
  assert.equal(calls.length, 3)
  for (const i of [0, 2]) {
    assert.equal(calls[i].init.body, body)
    assert.equal(calls[i].init.headers.get('Idempotency-Key'), 'stable')
  }
})

test('definitive refresh 401 clears state; transient refresh failures preserve it', async () => {
  for (const status of [401, 403, 429, 503]) {
    const app = setup({ initial: token({ exp: 1 }), fetch: async () => json({ detail: 'failure' }, status) })
    await assert.rejects(app.authenticatedFetch('/api/v1/jobs'))
    assert.equal(Boolean(app.authState.token), status !== 401)
  }
})

test('legacy unexpired credentials exchange once for a cookie session', async () => {
  const calls = []
  const app = setup({ initial: token({ sid: null }), fetch: async (url, init) => {
    calls.push(url)
    if (url.endsWith('/session')) {
      assert.equal(init.headers['X-Session-Request'], '1')
      assert.ok(init.headers.Authorization)
      return json({ access_token: token() })
    }
    return json({ id: 'user-1' })
  } })
  await app.fetchCurrentUser()
  await app.fetchCurrentUser()
  assert.equal(calls.filter(url => url.endsWith('/session')).length, 1)
  assert.equal(app.authState.sessionId, 'session-1')
})

test('hidden polling cannot extend expired credentials or delete them', async () => {
  const app = setup({ hidden: true, initial: token({ exp: 1 }), fetch: async url => {
    assert.ok(!url.includes('/auth/'))
    return json({ detail: 'expired' }, 401)
  } })
  const response = await app.authenticatedFetch('/api/v1/jobs')
  assert.equal(response.status, 401)
  assert.ok(app.authState.token)
})

test('a late refresh response cannot resurrect a logged-out session', async () => {
  let resolve
  const pending = new Promise(r => { resolve = r })
  const app = setup({ initial: token({ exp: 1 }), fetch: async url => {
    if (url.endsWith('/refresh')) return pending
    if (url.endsWith('/logout')) return new Response(null, { status: 204 })
    throw new Error('unexpected API call after logout')
  } })
  const request = app.authenticatedFetch('/api/v1/jobs')
  const result = assert.rejects(request)
  const logout = app.logout()
  resolve(json({ access_token: token() }))
  await Promise.all([result, logout])
  assert.equal(app.authState.token, null)
  assert.ok(!app.storage.has(key))
})

test('cross-tab refresh reuses the token already saved by another tab after acquiring its lock', async () => {
  const fresh = token()
  let app
  app = setup({ initial: token({ exp: 1 }), locks: { request: async (_name, action) => {
    app.storage.set(key, fresh)
    return await action()
  } }, fetch: async (url, init) => {
    assert.ok(!url.includes('/auth/'))
    assert.equal(init.headers.get('Authorization'), `Bearer ${fresh}`)
    return json({})
  } })
  await app.authenticatedFetch('/api/v1/jobs')
  assert.equal(app.authState.token, fresh)
})

test('cross-tab account switch prevents replaying a request under a different account', async () => {
  let app
  app = setup({ initial: token({ exp: 1 }), locks: { request: async (_name, action) => {
    app.storage.set(key, token({ sub: 'other-user', sid: 'other-session' }))
    return await action()
  } }, fetch: async () => { throw new Error('must not send') } })
  await assert.rejects(app.authenticatedFetch('/api/v1/jobs'), /登录状态已变化/)
})

test('external origins never receive credentials and aborted requests never submit', async () => {
  const app = setup({ fetch: async () => { throw new Error('must not send') } })
  await assert.rejects(app.authenticatedFetch('https://external.test/api/v1/jobs'), /不支持/)
  await assert.rejects(app.authenticatedFetch('/api/v1/jobs', { signal: AbortSignal.abort() }), /Aborted/)
})


test('refresh cannot switch to another account or another login session', async () => {
  for (const replacement of [token({ sub: 'other-user' }), token({ sid: 'other-session' })]) {
    const app = setup({ initial: token({ exp: 1 }), fetch: async () => json({ access_token: replacement }) })
    const original = app.authState.token
    await assert.rejects(app.authenticatedFetch('/api/v1/jobs'), /会话不匹配/)
    assert.equal(app.authState.token, original)
  }
})

test('a stale profile response cannot populate another account after a storage event', async () => {
  let resolve
  const pending = new Promise(r => { resolve = r })
  const app = setup({ fetch: async () => pending })
  const request = app.fetchCurrentUser()
  app.storage.set(key, token({ sub: 'other-user', sid: 'other-session' }))
  app.listeners.storage({ key })
  resolve(json({ id: 'user-1' }))
  await request
  assert.equal(app.authState.user, null)
  assert.equal(app.authState.sessionId, 'other-session')
})

test('private image downloads refresh expired access while external media never receives credentials', async () => {
  const fresh = token()
  const app = setup({ initial: token({ exp: 1 }), fetch: async (url, init) => {
    if (url.endsWith('/refresh')) return json({ access_token: fresh })
    if (url.startsWith('/api/')) {
      assert.equal(init.headers.get('Authorization'), `Bearer ${fresh}`)
    } else {
      assert.equal(init.headers.get('Authorization'), null)
      assert.equal(init.credentials, 'omit')
    }
    return new Response('image bytes')
  } })
  assert.equal((await app.fetchImageFile('/api/v1/jobs/image/file')).status, 200)
  assert.equal((await app.fetchImageFile('https://external.test/image.png', {
    headers: { Authorization: 'must-not-leak' }, credentials: 'include',
  })).status, 200)
})
