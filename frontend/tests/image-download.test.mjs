import { test } from 'node:test'
import assert from 'node:assert/strict'
import { downloadObjectUrl } from '../src/lib/image-download.ts'

test('image preview download uses an attached anchor download instead of navigating to its blob URL', () => {
  const previous = globalThis.document
  const appended = [], clicks = [], removed = []
  globalThis.document = {
    body: { appendChild: anchor => appended.push(anchor) },
    createElement: tag => {
      assert.equal(tag, 'a')
      return { click() { clicks.push(this.href) }, remove() { removed.push(this.href) } }
    },
  }
  try {
    downloadObjectUrl('blob:https://app.example/image', 'job-123', 'image/webp')
    assert.equal(appended.length, 1)
    assert.equal(appended[0].href, 'blob:https://app.example/image')
    assert.equal(appended[0].download, 'job-123.webp')
    assert.equal(appended[0].rel, 'noopener')
    assert.deepEqual(clicks, ['blob:https://app.example/image'])
    assert.deepEqual(removed, ['blob:https://app.example/image'])
  } finally {
    if (previous === undefined) delete globalThis.document
    else globalThis.document = previous
  }
})
