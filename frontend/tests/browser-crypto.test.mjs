import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash, webcrypto } from 'node:crypto'
import { randomId, sha256Hex } from '../src/lib/browser-crypto.ts'

test('HTTP fallback generates v4 UUIDs using the browser random source', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
  })
  try {
    const ids = Array.from({ length: 100 }, randomId)
    assert.equal(new Set(ids).size, 100)
    for (const id of ids)
      assert.match(
        id,
        /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/,
      )
  } finally {
    Object.defineProperty(globalThis, 'crypto', original)
  }
})

test('HTTP and HTTPS asset hashes match server SHA-256 at padding boundaries', async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  try {
    for (const native of [true, false]) {
      Object.defineProperty(globalThis, 'crypto', {
        configurable: true,
        value: native ? webcrypto : {},
      })
      for (const size of [0, 1, 55, 56, 63, 64, 65, 1024 * 1024]) {
        const input = Uint8Array.from({ length: size }, (_, i) => i % 251)
        assert.equal(
          await sha256Hex(input.buffer),
          createHash('sha256').update(input).digest('hex'),
        )
      }
    }
  } finally {
    Object.defineProperty(globalThis, 'crypto', original)
  }
})
