export function mediaAvailable(state: string, expiresAt: string | null | undefined, now = Date.now()): boolean {
  if (state !== 'available') return false
  if (!expiresAt) return true
  const expiry = Date.parse(expiresAt)
  return Number.isFinite(expiry) && expiry > now
}

export function expiryText(state: string, expiresAt: string | null | undefined, permanent: boolean, now = Date.now()): string {
  if (state === 'none') return '暂无生成图片'
  if (state === 'expired' || (expiresAt && Date.parse(expiresAt) <= now)) return '图片已过期'
  if (state !== 'available') return '作品已失效'
  if (permanent) return '已长期保存'
  if (!expiresAt) return '有效期未提供'
  const expires = Date.parse(expiresAt)
  if (!Number.isFinite(expires)) return '有效期未提供'
  const remaining = expires - now
  const text = new Date(expires).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
  const left = remaining >= 3600000 ? `${Math.ceil(remaining / 3600000)} 小时` : `${Math.max(1, Math.ceil(remaining / 60000))} 分钟`
  return `${text} 到期 · 剩余 ${left}`
}

export function retryableMediaStatus(status: number): boolean {
  return status === 408 || status === 429 || status >= 500
}

export function sameOriginMedia(src: string, origin: string): boolean {
  try {
    const url = new URL(src, origin)
    return /^https?:$/.test(url.protocol) && url.origin === origin
  } catch { return false }
}
