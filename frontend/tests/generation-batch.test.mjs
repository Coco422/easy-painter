import { test } from 'node:test'
import assert from 'node:assert/strict'
import { submitGenerationBatch, validGenerationCount } from '../src/lib/generation-batch.ts'

const noWait = async () => {}
test('custom batch counts accept positive integers without a four-image ceiling', () => {
  for (const count of [1, 7, 25, 1000]) assert.equal(validGenerationCount(count), true)
  for (const count of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) assert.equal(validGenerationCount(count), false)
})

test('large batches submit all images with bounded in-flight requests and accurate charges', async () => {
  let active = 0, maximum = 0, registered = 0
  const result = await submitGenerationBatch(25, async () => {
    maximum = Math.max(maximum, ++active)
    await new Promise(resolve => setImmediate(resolve))
    active--
    return { credit_cost: 3 }
  }, { isCurrent: () => true, onSuccess: () => registered++, wait: noWait })
  assert.equal(maximum, 4)
  assert.equal(registered, 25)
  assert.deepEqual(result, { accepted: 25, failed: 0, reserved: 75, remaining: 0, error: undefined })
})

test('a balance or flood refusal stops the rest of the batch and preserves accepted jobs', async () => {
  for (const status of [402, 429, 503]) {
    let calls = 0
    const refusal = Object.assign(new Error('refused'), { status })
    const result = await submitGenerationBatch(1000000, async () => {
      if (++calls > 2) throw refusal
      return { credit_cost: 5 }
    }, { isCurrent: () => true, onSuccess: () => {}, wait: noWait })
    assert.equal(calls, 4)
    assert.equal(result.accepted, 2)
    assert.equal(result.reserved, 10)
    assert.equal(result.remaining, 999996)
    assert.equal(result.error, refusal)
  }
})

test('changing accounts during submission cannot register results or start later requests', async () => {
  let current = true, registered = 0, calls = 0
  const result = await submitGenerationBatch(25, async () => {
    calls++; current = false
    return { credit_cost: 5 }
  }, { isCurrent: () => current, onSuccess: () => registered++, wait: noWait })
  assert.equal(calls, 4)
  assert.equal(registered, 0)
  assert.equal(result.remaining, 25)
})


test('stopping a batch retains accepted in-flight jobs without submitting the rest', async () => {
  let stop=false, registered=0
  const result=await submitGenerationBatch(25,async () => ({credit_cost:5}),{
    isCurrent:() => true, shouldContinue:() => !stop,
    onSuccess:() => {registered++;stop=true}, wait:noWait,
  })
  assert.equal(registered,4)
  assert.equal(result.accepted,4)
  assert.equal(result.reserved,20)
  assert.equal(result.remaining,21)
})
