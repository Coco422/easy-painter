// Development-only API mock for the creation workspace.
// Registered by vite.config.ts. Browser requests hit /__mock/* for control and
// normal /api/v1/* paths are answered from the selected scenario.
import type { Connect, Plugin } from 'vite'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { mockModels, mockScenarios, mockUser, type MockJobSeed, type MockScenario } from './scenarios'

interface JobRecord {
  job_id: string
  prompt: string
  model: string
  model_label: string
  size: string
  status: 'queued' | 'processing' | 'succeeded' | 'failed'
  billing_status: string
  credit_cost: number
  created_at: string
  finished_at: string | null
  error_message: string | null
  media_state: string
  media_expires_at: string | null
  broken_media: boolean
  parent: string | null
  batch: string
}

const SCENARIO_COOKIE = 'ep_mock_scenario'
const T0_COOKIE = 'ep_mock_t0'
const SESSION_COOKIE = 'ep_mock_session'

function parseCookies(request: IncomingMessage): Record<string, string> {
  return Object.fromEntries((request.headers.cookie ?? '').split(';').map(part => {
    const index = part.indexOf('=')
    return index < 0 ? ['', ''] : [part.slice(0, index).trim(), decodeURIComponent(part.slice(index + 1).trim())]
  }).filter(([key]) => key))
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise(resolve => {
    const chunks: Buffer[] = []
    request.on('data', (chunk: Buffer) => chunks.push(chunk))
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    request.on('error', () => resolve(''))
  })
}

function json(response: ServerResponse, status: number, payload: unknown) {
  const body = JSON.stringify(payload)
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
  response.end(body)
}

function readCookie(request: IncomingMessage, name: string): string | null {
  return parseCookies(request)[name] ?? null
}

function setCookies(response: ServerResponse, values: Record<string, string>) {
  response.setHeader('Set-Cookie', Object.entries(values).map(([key, value]) =>
    `${key}=${encodeURIComponent(value)}; Path=/; SameSite=Lax; Max-Age=86400`))
}

function nowIso(offsetSeconds: number) {
  return new Date(Date.now() + offsetSeconds * 1000).toISOString()
}

function mockCostForSize(model: (typeof mockModels)[number], size: string) {
  const match = /^(\d+)x(\d+)$/.exec(size)
  const longEdge = match ? Math.max(Number(match[1]), Number(match[2])) : 0
  const tier = longEdge > 2560 ? '4k' : longEdge > 1792 ? '2k' : '1k'
  return model.credit_cost_by_size?.[size] ?? model.credit_cost_by_size?.[tier] ?? model.credit_cost
}

/** Deterministic, cheap landscape/portrait artwork so media tests have a real image. */
function sceneSvg(seed: string, width: number, height: number) {
  let hash = 2166136261
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  const pick = (offset: number, mod: number) => Math.abs((hash >> offset) & 0xff) % mod
  const hue = pick(0, 360)
  const skyTop = `hsl(${hue} 32% 32%)`
  const skyLow = `hsl(${(hue + 28) % 360} 46% 58%)`
  const ground = `hsl(${(hue + 200) % 360} 22% 22%)`
  const body = [
    `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">`,
    `<stop offset="0" stop-color="${skyTop}"/><stop offset=".62" stop-color="${skyLow}"/>`,
    `<stop offset="1" stop-color="${ground}"/></linearGradient></defs>`,
    `<rect width="${width}" height="${height}" fill="url(#g)"/>`,
    `<circle cx="${(width * (20 + pick(4, 60)) / 100).toFixed(0)}" cy="${(height * (12 + pick(8, 18)) / 100).toFixed(0)}" r="${(Math.min(width, height) * 0.07).toFixed(0)}" fill="hsl(${(hue + 340) % 360} 72% 74%)" opacity=".9"/>`,
    `<path d="M0 ${height * 0.72} L${width * 0.24} ${height * 0.5} L${width * 0.48} ${height * 0.68} L${width * 0.7} ${height * 0.44} L${width} ${height * 0.66} L${width} ${height} L0 ${height} Z" fill="hsl(${(hue + 190) % 360} 24% 18%)"/>`,
    `<path d="M0 ${height} L${width * 0.18} ${height * 0.7} L${width * 0.52} ${height * 0.82} L${width * 0.86} ${height * 0.62} L${width} ${height * 0.8} L${width} ${height} Z" fill="hsl(${(hue + 205) % 360} 20% 12%)"/>`,
    `<rect x="${width * 0.72}" y="${height * 0.28}" width="${width * 0.03}" height="${height * 0.42}" fill="hsl(${(hue + 40) % 360} 18% 20%)" opacity=".85"/>`,
  ].join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${body}</svg>`
}

function dimensions(size: string) {
  const match = /^(\d+)x(\d+)$/.exec(size)
  if (match) return { width: Number(match[1]), height: Number(match[2]) }
  return { width: 1024, height: 1024 }
}

export function easyPainterMock(): Plugin {
  const created: JobRecord[] = []

  function scenarioFor(request: IncomingMessage): { name: string; scenario: MockScenario; t0: number } {
    const name = readCookie(request, SCENARIO_COOKIE) ?? 'idle'
    const scenario = mockScenarios[name] ?? mockScenarios['idle']
    const raw = Number(readCookie(request, T0_COOKIE) ?? '')
    return { name, scenario, t0: Number.isFinite(raw) && raw > 0 ? raw : Date.now() }
  }

  function buildJobs(scenario: MockScenario, t0: number): JobRecord[] {
    const withSeed = (seed: MockJobSeed, index: number): JobRecord => {
      const model = mockModels.find(item => item.id === (seed.model ?? 'gpt-image-2')) ?? mockModels[0]
      const settle = seed.settleAfter ?? -60
      const fail = seed.failAfter
      const age = (scenario.ageMinutes ?? 0) * 60
      const startedAt = t0 + Math.min(settle, fail ?? settle) * 1000 + age * 1000
      const createdAt = new Date(startedAt).toISOString()
      const ready = (settle <= 0 || Date.now() > t0 + settle * 1000)
      const failed = fail !== undefined && (fail <= 0 || Date.now() > t0 + fail * 1000)
      const expires = seed.expiresInHours === null ? null
        : new Date(Date.now() + (seed.expiresInHours ?? 48) * 3600 * 1000).toISOString()
      const status: JobRecord['status'] = failed ? 'failed' : ready ? 'succeeded' : Date.now() > t0 + Math.min(settle, 4000) * 1000 ? 'processing' : 'queued'
      return {
        job_id: seed.id || `job-${index}`,
        prompt: seed.prompt,
        model: model.id,
        model_label: model.label,
        size: seed.size ?? '1024x1024',
        status,
        billing_status: status === 'failed' ? 'refunded' : status === 'succeeded' ? 'settled' : 'reserved',
        credit_cost: seed.creditCost ?? mockCostForSize(model, seed.size ?? '1024x1024'),
        created_at: createdAt,
        finished_at: status === 'succeeded' || status === 'failed' ? new Date(startedAt + 9000).toISOString() : null,
        error_message: failed ? seed.errorMessage ?? '生成失败，费用已全额退回。' : null,
        media_state: seed.mediaState ?? 'available',
        media_expires_at: seed.mediaState === 'none' ? null : expires,
        broken_media: Boolean(seed.brokenMedia),
        parent: seed.parent ?? null,
        batch: seed.batch ?? `batch-${index}`,
      }
    }
    return [...scenario.jobs.map(withSeed), ...created]
  }

  function decorate(job: JobRecord) {
    return {
      job_id: job.job_id,
      status: job.status,
      image_url: job.status === 'succeeded' ? `/api/v1/jobs/${job.job_id}/media` : null,
      thumbnail_url: job.status === 'succeeded' ? `/api/v1/jobs/${job.job_id}/media` : null,
      prompt: job.prompt,
      revised_prompt: null,
      model: job.model,
      model_label: job.model_label,
      provider_name: 'mock-upstream',
      size: job.size,
      aspect_ratio: null,
      error_message: job.error_message,
      credit_cost: job.credit_cost,
      billing_status: job.billing_status,
      refunded_at: job.status === 'failed' ? job.finished_at : null,
      created_at: job.created_at,
      finished_at: job.finished_at,
      media_state: job.media_state,
      media_expires_at: job.media_expires_at,
      retention_kind: 'standard',
    }
  }

  async function handleMock(request: IncomingMessage, response: ServerResponse, pathname: string, search: URLSearchParams) {
    if (pathname === '/__mock/scenarios') {
      json(response, 200, Object.entries(mockScenarios).map(([name, scenario]) => ({
        name, label: scenario.label, detail: scenario.detail,
      })))
      return
    }
    if (pathname === '/__mock/state') {
      const { name, t0 } = scenarioFor(request)
      // Persist the scenario clock. Without this every request mints a new t0,
      // which changes the token and makes the client reload in a loop.
      if (readCookie(request, SESSION_COOKIE) !== '1' || readCookie(request, T0_COOKIE) !== String(t0) || readCookie(request, SCENARIO_COOKIE) !== name) {
        setCookies(response, { [SESSION_COOKIE]: '1', [SCENARIO_COOKIE]: name, [T0_COOKIE]: String(t0) })
      }
      const owner = mockUser.id
      const jobs = buildJobs(mockScenarios[name] ?? mockScenarios['idle'], t0)
      const membership: Record<string, string> = {}
      const parents: Record<string, string | null> = {}
      for (const job of jobs) {
        membership[job.job_id] = job.batch
        parents[job.job_id] = job.parent
      }
      const token = fakeToken(t0)
      json(response, 200, {
        scenario: name,
        token,
        user: mockUser,
        storage: {
          'easy-painter:job-batches': JSON.stringify(membership),
          [`easy-painter:creation-versions:${owner}`]: JSON.stringify({ parents, pending: null }),
        },
      })
      return
    }
    if (pathname === '/__mock/disable') {
      setCookies(response, { [SESSION_COOKIE]: '0' })
      json(response, 200, { ok: true })
      return
    }
    if (pathname === '/__mock/select') {
      const name = search.get('name') ?? 'idle'
      setCookies(response, { [SCENARIO_COOKIE]: name, [T0_COOKIE]: String(Date.now()) })
      created.length = 0
      json(response, 200, { ok: true, scenario: name })
      return
    }
    if (pathname === '/__mock/restart') {
      // Re-pin t0 so timed scenarios replay from the beginning.
      setCookies(response, { [T0_COOKIE]: String(Date.now()) })
      created.length = 0
      json(response, 200, { ok: true })
      return
    }
  }

  function fakeToken(seed: number) {
    // Fully derived from t0: a stable token is what stops the client reloading.
    const payload = { sub: mockUser.id, sid: `mock-${seed}`, typ: 'access', exp: Math.floor(seed / 1000) + 86400 * 30 }
    const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url')
    return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(payload)}.mock`
  }

  async function handleApi(request: IncomingMessage, response: ServerResponse, pathname: string, search: URLSearchParams) {
    const { scenario, t0 } = scenarioFor(request)
    const method = request.method ?? 'GET'
    const jobs = () => buildJobs(scenario, t0)

    if (pathname === '/api/v1/meta/public') {
      json(response, 200, {
        site_name: '一丝绘画站 · 设计预览',
        registration_enabled: true,
        email_delivery_enabled: true,
        prompt_max_length: 4000,
        polling_interval_ms: 1200,
        example_prompts: [lighthouseText()],
        models: scenario.models ?? mockModels,
        viewer_group: { code: 'mock', name: '演示组', billing_multiplier_bps: 10000, generated_retention_hours: 48, reference_retention_hours: 48, max_reference_images: 5 },
      })
      return
    }
    if (pathname === '/api/v1/stats/public') {
      json(response, 200, { today_images: 128, total_images: 24581 })
      return
    }
    if (pathname === '/api/v1/announcements') {
      json(response, 200, [])
      return
    }
    if (pathname === '/api/v1/users/me') {
      json(response, 200, { ...mockUser, credits: scenario.credits })
      return
    }
    if (pathname === '/api/v1/auth/login' || pathname === '/api/v1/auth/register' || pathname === '/api/v1/auth/refresh') {
      json(response, 200, { access_token: fakeToken(Date.now()), token_type: 'bearer' })
      return
    }
    if (pathname === '/api/v1/auth/logout') {
      json(response, 204, undefined)
      return
    }
    if (pathname === '/api/v1/jobs/active') {
      json(response, 200, jobs().filter(job => job.status === 'queued' || job.status === 'processing').map(decorate))
      return
    }
    const mediaMatch = /^\/api\/v1\/jobs\/([^/]+)\/media$/.exec(pathname)
    if (mediaMatch) {
      const job = jobs().find(item => item.job_id === mediaMatch[1])
      if (!job || job.broken_media || job.media_state !== 'available' || job.status !== 'succeeded') {
        json(response, 404, { detail: '图片不可用' })
        return
      }
      const { width, height } = dimensions(job.size)
      const svg = sceneSvg(job.prompt, width, height)
      response.writeHead(200, {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'no-store',
        'Content-Length': String(Buffer.byteLength(svg)),
      })
      response.end(svg)
      return
    }
    const jobMatch = /^\/api\/v1\/jobs\/([^/]+)$/.exec(pathname)
    if (jobMatch && method === 'GET') {
      const job = jobs().find(item => item.job_id === jobMatch[1])
      if (!job) { json(response, 404, { detail: '任务不存在' }); return }
      json(response, 200, decorate(job))
      return
    }
    if (pathname === '/api/v1/jobs' && method === 'POST') {
      const body = JSON.parse((await readBody(request)) || '{}') as { prompt?: string; model?: string; size?: string }
      if (scenario.submit === 'insufficient') {
        json(response, 402, { detail: { message: '灵感丝线不足', required: 5, balance: scenario.credits } })
        return
      }
      if (scenario.submit === 'unknown') {
        json(response, 503, { detail: '上游暂时不可用' })
        return
      }
      if (scenario.submit === 'slow') await new Promise(resolve => setTimeout(resolve, 2500))
      const model = mockModels.find(item => item.id === (body.model ?? '')) ?? mockModels[0]
      const record: JobRecord = {
        job_id: `job-${Date.now().toString(36)}-${created.length + 1}`,
        prompt: body.prompt ?? '',
        model: model.id,
        model_label: model.label,
        size: body.size ?? 'auto',
        status: 'queued',
        billing_status: 'reserved',
        credit_cost: mockCostForSize(model, body.size ?? '1024x1024'),
        created_at: new Date().toISOString(),
        finished_at: null,
        error_message: null,
        media_state: 'available',
        media_expires_at: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
        broken_media: false,
        parent: null,
        batch: 'batch-new',
      }
      // New submissions settle after four seconds so the waiting state is observable.
      setTimeout(() => {
        record.status = 'succeeded'
        record.billing_status = 'settled'
        record.finished_at = new Date().toISOString()
      }, 4000)
      created.push(record)
      json(response, 200, {
        job_id: record.job_id,
        status: 'queued',
        poll_url: `/api/v1/jobs/${record.job_id}`,
        credit_cost: record.credit_cost,
        base_credit_cost: model.base_credit_cost,
        billing_multiplier_bps: 10000,
        group_code: 'mock',
        group_name: '演示组',
        balance_after: scenario.credits - record.credit_cost,
        billing_status: 'reserved',
      })
      return
    }
    if (pathname === '/api/v1/reference-images' && method === 'POST') {
      json(response, 200, {
        id: `ref-${Date.now()}`, filename: '参考图.png', content_type: 'image/png',
        used_count: 0, created_at: new Date().toISOString(), last_used_at: null,
        media_state: 'available', media_expires_at: null, thumbnail_url: null,
      })
      return
    }
    if (pathname === '/api/v1/reference-images') {
      json(response, 200, { items: [], total: 0, page: 1, page_size: 50 })
      return
    }
    const referenceMatch = /^\/api\/v1\/reference-images\/([^/]+)(\/file)?$/.exec(pathname)
    if (referenceMatch) {
      if (referenceMatch[2]) {
        const svg = sceneSvg(referenceMatch[1], 512, 512)
        response.writeHead(200, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'no-store' })
        response.end(svg)
        return
      }
      json(response, 204, undefined)
      return
    }
    const artworkMatch = /^\/api\/v1\/artworks\/job\/([^/]+)$/.exec(pathname)
    if (artworkMatch) {
      const job = jobs().find(item => item.job_id === artworkMatch[1])
      if (!job) { json(response, 404, { detail: '作品不存在' }); return }
      json(response, 200, {
        kind: 'job', id: `art-${job.job_id}`, job_id: job.job_id, inspiration_id: null, favorite_id: null,
        title: job.prompt.slice(0, 30), prompt: job.prompt, revised_prompt: null,
        is_prompt_public: false, can_view_prompt: true, username: mockUser.username, is_owner: true,
        is_in_gallery: false, gallery_visible: false, is_favorite: false, tags: [],
        status: job.status, model: job.model, size: job.size, aspect_ratio: 'auto',
        created_at: job.created_at, finished_at: job.finished_at, favorited_at: null,
        credit_cost: job.credit_cost, billing_status: job.billing_status, error_message: job.error_message,
        media_state: job.media_state, media_expires_at: job.media_expires_at, original_expires_at: job.media_expires_at,
        retention_kind: 'standard', image_url: job.status === 'succeeded' ? `/api/v1/jobs/${job.job_id}/media` : null,
        thumbnail_url: null, submission_status: 'none', review_reason: null,
      })
      return
    }
    void search
    json(response, 404, { detail: `未模拟的接口：${method} ${pathname}` })
  }

  const middleware: Connect.NextHandleFunction = (request, response, next) => {
    const url = new URL(request.url ?? '/', 'http://mock.local')
    if (url.pathname.startsWith('/__mock/')) {
      void handleMock(request, response, url.pathname, url.searchParams).catch(() => {
        if (!response.headersSent) json(response, 500, { detail: 'mock 处理失败' })
      })
      return
    }
    if (url.pathname.startsWith('/api/')) {
      // The frontend can opt out of the mock and use Vite's normal API proxy.
      if (readCookie(request, SESSION_COOKIE) === '0') {
        next()
        return
      }
      void handleApi(request, response, url.pathname, url.searchParams).catch(() => {
        if (!response.headersSent) json(response, 500, { detail: 'mock 处理失败' })
      })
      return
    }
    next()
  }

  return {
    name: 'easy-painter-dev-mock',
    apply: 'serve',
    configureServer(vite) {
      vite.middlewares.use(middleware)
    },
  }
}

function lighthouseText() {
  return '悬崖边的灯塔，黄昏，湿润的空气，远处有雨'
}

export type { MockScenario }
