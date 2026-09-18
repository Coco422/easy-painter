import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mediaAvailable, expiryText, retryableMediaStatus, sameOriginMedia } from '../src/lib/media-state.ts'
const now = Date.parse('2026-09-18T12:00:00Z')
test('the exact deadline, deleted media and invalid dates deny all media actions', () => {
  assert.equal(mediaAvailable('available', '2026-09-18T12:00:00Z', now), false)
  assert.equal(mediaAvailable('available', '2026-09-18T12:00:00.001Z', now), true)
  for (const state of ['expired', 'deleted', 'delete_pending', 'unavailable', 'none']) assert.equal(mediaAvailable(state, null, now), false)
  assert.equal(mediaAvailable('available', 'invalid', now), false)
  assert.equal(mediaAvailable('available', null, now), true)
})
test('expiry labels distinguish permanent copies from unknown deadlines', () => {
  assert.equal(expiryText('available', null, true, now), '已长期保存')
  assert.equal(expiryText('available', null, false, now), '有效期未提供')
  assert.equal(expiryText('available', '2026-09-18T12:00:00Z', false, now), '图片已过期')
  assert.match(expiryText('available', '2026-09-18T12:01:00Z', false, now), /剩余 1 分钟/)
  assert.match(expiryText('available', '2026-09-20T12:00:00Z', false, now), /剩余 48 小时/)
  assert.equal(expiryText('none', null, false, now), '暂无生成图片')
})
test('authorization failures and expired URLs cannot enter the retry loop', () => {
  for (const code of [400,401,403,404,410,422]) assert.equal(retryableMediaStatus(code), false)
  for (const code of [408,429,500,502,503]) assert.equal(retryableMediaStatus(code), true)
})
test('external media never receives user or admin credentials', () => {
  const origin = 'https://paint.example'
  for (const src of ['/api/v1/artworks/job/1/file', `${origin}/api/v1/inspirations/1/file`]) assert.equal(sameOriginMedia(src, origin), true)
  for (const src of ['https://images.example/1.jpg', '//images.example/1.jpg', 'https://paint.example@images.example/1.jpg', 'http://paint.example/1.jpg', 'https://paint.example:444/1.jpg', 'blob:https://paint.example/id', 'data:image/png;base64,AA==', 'https://[invalid']) assert.equal(sameOriginMedia(src, origin), false)
})
