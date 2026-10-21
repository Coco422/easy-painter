import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as vue from 'vue'
import * as quips from '../src/lib/generation-quips.ts'
import { compileModule } from './helpers/vue-renderer.mjs'

const source = fs.readFileSync(new URL('../src/composables/useGenerationQuips.ts', import.meta.url), 'utf8')
function setup(random, initialJobs = ['a', 'b', 'c', 'd'].map(job_id => ({ job_id, status: 'queued' }))) {
  const clock = vue.ref(1000)
  const jobs = vue.ref(initialJobs)
  const { useGenerationQuips } = compileModule(source, { vue, './useMediaClock': { useMediaClock: () => clock }, '@/lib/generation-quips': quips })
  const scope = vue.effectScope()
  const frames = scope.run(() => useGenerationQuips(jobs, random))
  return { clock, jobs, frames, scope }
}

test('the expanded pool has at least 96 unique lines and retains the original studio chatter', () => {
  assert.ok(quips.GENERATION_QUIPS.length >= 96)
  assert.equal(new Set(quips.GENERATION_QUIPS).size, quips.GENERATION_QUIPS.length)
  assert.ok(quips.GENERATION_QUIPS.includes('给云层办理临时身份证'))
  assert.ok(quips.GENERATION_QUIPS.includes('正在给画面取一个临时小名'))
})

test('draws can reach both ends of the pool and exclude only the previous line of the same job', () => {
  const first = quips.nextGenerationQuip(0, undefined, () => 0)
  assert.equal(first.index, 0)
  assert.equal(first.nextAt, 4500)
  const last = quips.nextGenerationQuip(0, undefined, () => .999999)
  assert.equal(last.index, quips.GENERATION_QUIPS.length - 1)
  assert.ok(last.nextAt <= 7500)
  for (let index = 0; index < quips.GENERATION_QUIPS.length; index++) {
    for (const random of [0, .5, .999999]) {
      const next = quips.nextGenerationQuip(100, { ...first, index, sequence: 8 }, () => random)
      assert.notEqual(next.index, index)
      assert.equal(next.sequence, 9)
      assert.equal(next.text, quips.GENERATION_QUIPS[next.index])
    }
  }
})

test('four simultaneous jobs draw their own lines and deadlines and advance independently', async () => {
  const values = [0, 0, .2, .9, .4, .4, .6, .6, .8, .5]
  let draws = 0
  const view = setup(() => values[draws++])
  try {
    assert.equal(draws, 8, 'each job draws a line and an independent rotation delay')
    const initial = [...view.frames.value.values()]
    assert.equal(new Set(initial.map(frame => frame.text)).size, 4)
    assert.equal(new Set(initial.map(frame => frame.nextAt)).size, 4)
    view.clock.value = initial[0].nextAt
    await vue.nextTick()
    assert.equal(draws, 10)
    assert.notEqual(view.frames.value.get('a'), initial[0])
    for (const [index, id] of ['b', 'c', 'd'].entries()) assert.equal(view.frames.value.get(id), initial[index + 1])
  } finally { view.scope.stop() }
})

test('independent random draws allow coincidental matches across jobs', () => {
  const view = setup(() => 0)
  try {
    assert.equal(view.frames.value.size, 4)
    assert.equal(new Set([...view.frames.value.values()].map(frame => frame.text)).size, 1)
    assert.notEqual(view.frames.value.get('a'), view.frames.value.get('b'), 'matching text still has separate per-job state')
  } finally { view.scope.stop() }
})

test('polling and queue transitions preserve phrases; terminal jobs, removed jobs and disposal stop updates', async () => {
  let draws = 0
  const view = setup(() => { draws++; return .2 })
  const original = view.frames.value.get('a')
  view.jobs.value = view.jobs.value.map(job => ({ ...job, status: 'processing' }))
  await vue.nextTick()
  assert.equal(view.frames.value.get('a'), original)
  assert.equal(draws, 8)
  view.jobs.value[0].status = 'succeeded'
  view.jobs.value[1].status = 'failed'
  view.jobs.value.splice(2, 1)
  await vue.nextTick()
  assert.deepEqual([...view.frames.value.keys()], ['d'])
  view.clock.value += 9000
  await vue.nextTick()
  assert.equal(draws, 10)
  view.scope.stop()
  view.clock.value += 9000
  await vue.nextTick()
  assert.equal(draws, 10)
})
