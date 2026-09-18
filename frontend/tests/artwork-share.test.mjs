import { test } from 'node:test'
import assert from 'node:assert/strict'
import { artworkShare } from '../src/lib/artwork-share.ts'

const origin = 'https://paint.example'
const now = Date.parse('2026-09-18T12:00:00Z')
const original = {
  media_state: 'available', media_expires_at: '2026-09-20T12:00:00Z',
  image_url: '/api/v1/artworks/job/private/file?token=private-token',
  retention_kind: 'temporary', inspiration_id: null,
  gallery_visible: false, username: '画家 / 1',
  is_owner: true, is_in_gallery: false, is_prompt_public: false,
  prompt: 'private prompt', title: 'private title', revised_prompt: 'private revision',
}

test('private history and a portfolio with its public master switch off cannot be shared', () => {
  assert.equal(artworkShare(original, origin, now), null)
  assert.equal(artworkShare({ ...original, is_in_gallery: true }, origin, now), null)
})

test('public portfolio sharing excludes private prompts, titles and authenticated media URLs', () => {
  const share = artworkShare({ ...original, gallery_visible: true }, origin, now)
  assert.deepEqual(share.data, {
    title: '个人画廊', text: '分享一个公开画廊',
    url: `${origin}/gallery/${encodeURIComponent(original.username)}`,
  })
  assert.doesNotMatch(JSON.stringify(share), /private/)
  assert.equal(artworkShare({ ...original, gallery_visible: true, username: null }, origin, now), null)
})

test('a permanent community copy shares its independent public URL after the original expires', () => {
  const share = artworkShare({
    ...original, retention_kind: 'permanent', inspiration_id: 'community-1',
    media_expires_at: null, original_expires_at: '2026-09-17T12:00:00Z',
  }, origin, now)
  assert.equal(share.data.url, `${origin}/api/v1/artworks/inspiration/community-1/file`)
  assert.doesNotMatch(JSON.stringify(share), /private/)
  assert.equal(artworkShare({ ...original, retention_kind: 'permanent' }, origin, now), null)
})

test('expired, withdrawn, missing and invalid media cannot be shared', () => {
  const publicItem = { ...original, gallery_visible: true }
  for (const state of ['expired', 'unavailable', 'deleted', 'delete_pending', 'none']) {
    assert.equal(artworkShare({ ...publicItem, media_state: state }, origin, now), null)
  }
  for (const deadline of ['2026-09-18T12:00:00Z', 'invalid']) {
    assert.equal(artworkShare({ ...publicItem, media_expires_at: deadline }, origin, now), null)
  }
  assert.equal(artworkShare({ ...publicItem, image_url: null }, origin, now), null)
  assert.equal(artworkShare({ ...publicItem, retention_kind: 'permanent', inspiration_id: 'removed', media_state: 'unavailable' }, origin, now), null)
})
