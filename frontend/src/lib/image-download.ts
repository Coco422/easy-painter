// Media URLs can contain access tokens and need not have a file extension.
export function imageDownloadFilename(id: string, contentType: string): string {
  const extensions: Record<string, string> = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/webp': 'webp',
    'image/gif': 'gif',
    'image/avif': 'avif',
    'image/svg+xml': 'svg',
  }
  const mime = contentType.split(';')[0].trim().toLowerCase()
  return `${id}.${extensions[mime] || 'bin'}`
}
