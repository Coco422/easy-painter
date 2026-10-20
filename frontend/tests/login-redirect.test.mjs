import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loginDestination } from '../src/lib/login-redirect.ts'

test('canvas login returns to the original local project, including query and hash', () => {
  for (const path of ['/canvas', '/canvas/', '/canvas/project-123', '/canvas/project-123?export=1#node', '/canvas?export=1']) {
    assert.equal(loginDestination(path), path)
  }
})

test('login ignores external, unrelated and malformed destinations', () => {
  for (const path of [undefined, null, ['/canvas'], 'https://example.com/canvas', '//example.com/canvas', '/canvas-other', '/profile', '/canvas\\evil', '/canvas\n//evil']) {
    assert.equal(loginDestination(path), '/')
  }
})
