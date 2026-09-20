// getRandomValues also works on HTTP origins, unlike randomUUID and subtle.
export function randomId(): string {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = globalThis.crypto.subtle
    ? new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', buffer))
    : (await import('@noble/hashes/sha2.js')).sha256(new Uint8Array(buffer))
  return Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('')
}
