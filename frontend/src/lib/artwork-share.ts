import type { Artwork } from './artworks'
import { mediaAvailable } from './media-state.ts'

type ShareableArtwork = Pick<Artwork, 'media_state' | 'media_expires_at' | 'image_url' | 'retention_kind' | 'inspiration_id' | 'gallery_visible' | 'username'>

export function artworkShare(item: ShareableArtwork, origin: string, now = Date.now()) {
  if (!item.image_url || !mediaAvailable(item.media_state, item.media_expires_at, now)) return null

  // A curated copy remains public independently of the original and its portfolio.
  if (item.retention_kind === 'permanent' && item.inspiration_id) {
    return {
      data: {
        title: '社区灵感', text: '分享一张社区收录作品',
        url: `${origin}/api/v1/artworks/inspiration/${encodeURIComponent(item.inspiration_id)}/file`,
      },
      copyNotice: '图片链接已复制',
    }
  }
  if (item.gallery_visible && item.username) {
    // Owner metadata can contain a hidden prompt; never include it in a share payload.
    return {
      data: {
        title: '个人画廊', text: '分享一个公开画廊',
        url: `${origin}/gallery/${encodeURIComponent(item.username)}`,
      },
      copyNotice: '画廊链接已复制',
    }
  }
  return null
}
