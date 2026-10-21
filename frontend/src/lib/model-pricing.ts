import type { ImageSize, PublicModel } from './types'

export function sizePricingTier(size: string): '1k' | '2k' | '4k' {
  const match = /^(\d+)x(\d+)$/.exec(String(size || 'auto').toLowerCase())
  if (!match) return '1k'
  const longEdge = Math.max(Number(match[1]), Number(match[2]))
  if (longEdge <= 1792) return '1k'
  if (longEdge <= 2560) return '2k'
  return '4k'
}

function priceFromMap(model: PublicModel, size: ImageSize | string, map: Record<string, number> | undefined, fallback: number) {
  const prices = map ?? {}
  const normalized = String(size || 'auto').toLowerCase()
  return prices[normalized] ?? prices[sizePricingTier(normalized)] ?? prices.auto ?? fallback
}

export function modelCreditCost(model: PublicModel | undefined, size: ImageSize | string) {
  return model ? priceFromMap(model, size, model.credit_cost_by_size, model.credit_cost) : 0
}

export function modelBaseCreditCost(model: PublicModel | undefined, size: ImageSize | string) {
  return model ? priceFromMap(model, size, model.base_credit_cost_by_size, model.base_credit_cost) : 0
}
