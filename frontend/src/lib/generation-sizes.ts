import type { ImageSize } from './types'

export const GENERATION_SIZE_OPTIONS: Array<{
  value: ImageSize
  label: string
  detail: string
  tier: 'auto' | '1k' | '2k' | '4k'
}> = [
  { value: '1024x1024', label: '1K 方图', detail: '1024 × 1024', tier: '1k' },
  { value: '1280x720', label: '1K 横图', detail: '1280 × 720', tier: '1k' },
  { value: '720x1280', label: '1K 竖图', detail: '720 × 1280', tier: '1k' },
  { value: '1536x1024', label: '1K 横图', detail: '1536 × 1024', tier: '1k' },
  { value: '1024x1536', label: '1K 竖图', detail: '1024 × 1536', tier: '1k' },
  { value: '1792x1024', label: '1K 横图', detail: '1792 × 1024', tier: '1k' },
  { value: '1024x1792', label: '1K 竖图', detail: '1024 × 1792', tier: '1k' },
  { value: '2048x2048', label: '2K 方图', detail: '2048 × 2048', tier: '2k' },
  { value: '2048x1152', label: '2K 横图', detail: '2048 × 1152', tier: '2k' },
  { value: '1152x2048', label: '2K 竖图', detail: '1152 × 2048', tier: '2k' },
  { value: '3840x2160', label: '4K 横图', detail: '3840 × 2160', tier: '4k' },
  { value: '2160x3840', label: '4K 竖图', detail: '2160 × 3840', tier: '4k' },
  { value: 'auto', label: '自动', detail: '按 1K 计费', tier: 'auto' },
]

export const DEFAULT_GENERATION_SIZES: ImageSize[] =
  GENERATION_SIZE_OPTIONS.map((option) => option.value)

export const DEFAULT_GENERATION_SIZE: ImageSize = '1024x1024'

export function defaultGenerationSize(supportedSizes: readonly string[] = []): ImageSize {
  if (!supportedSizes.length || supportedSizes.includes(DEFAULT_GENERATION_SIZE))
    return DEFAULT_GENERATION_SIZE
  return (GENERATION_SIZE_OPTIONS.find((option) => supportedSizes.includes(option.value))?.value
    ?? supportedSizes[0]
    ?? 'auto') as ImageSize
}

export function canvasGenerationSizes(supportedSizes: readonly string[] = []): string[] {
  if (!supportedSizes.length) return [...DEFAULT_GENERATION_SIZES]
  const supported = new Set(supportedSizes)
  return [
    ...GENERATION_SIZE_OPTIONS.map((option) => option.value).filter((size) => supported.has(size)),
    ...supportedSizes.filter((size) => !GENERATION_SIZE_OPTIONS.some((option) => option.value === size)),
  ]
}
