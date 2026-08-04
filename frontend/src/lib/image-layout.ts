export interface ImageLayout {
  aspectRatio: string
  ratio: number
  width?: number
  height?: number
  estimated: boolean
}

const SIZE_PATTERN = /^(\d+)x(\d+)$/
const ASPECT_RATIO_PATTERN = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/

export function resolveImageLayout(size?: string | null, aspectRatio?: string | null): ImageLayout {
  const sizeMatch = size?.match(SIZE_PATTERN)
  if (sizeMatch) {
    const width = Number(sizeMatch[1])
    const height = Number(sizeMatch[2])
    if (width > 0 && height > 0) {
      return {
        aspectRatio: `${width} / ${height}`,
        ratio: width / height,
        width,
        height,
        estimated: false,
      }
    }
  }

  const ratioMatch = aspectRatio?.match(ASPECT_RATIO_PATTERN)
  if (ratioMatch) {
    const width = Number(ratioMatch[1])
    const height = Number(ratioMatch[2])
    if (width > 0 && height > 0) {
      return {
        aspectRatio: `${width} / ${height}`,
        ratio: width / height,
        estimated: true,
      }
    }
  }

  return {
    aspectRatio: '1 / 1',
    ratio: 1,
    estimated: true,
  }
}
