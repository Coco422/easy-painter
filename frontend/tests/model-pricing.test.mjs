import assert from 'node:assert/strict'
import test from 'node:test'
import { modelBaseCreditCost, modelCreditCost, sizePricingTier } from '../src/lib/model-pricing.ts'

const model = {
  id: 'image',
  label: 'Image',
  enabled: true,
  supports_reference_image: true,
  max_reference_images: 5,
  supported_sizes: [],
  base_credit_cost: 5,
  credit_cost: 5,
  base_credit_cost_by_size: { '1k': 5, '2k': 8, '4k': 12 },
  credit_cost_by_size: { '1k': 5, '2k': 8, '4k': 12 },
}

test('resolution sizes use matching price tiers', () => {
  assert.equal(sizePricingTier('auto'), '1k')
  assert.equal(sizePricingTier('1024x1792'), '1k')
  assert.equal(sizePricingTier('2048x2048'), '2k')
  assert.equal(sizePricingTier('3840x2160'), '4k')
  assert.equal(modelCreditCost(model, '2048x2048'), 8)
  assert.equal(modelBaseCreditCost(model, '3840x2160'), 12)
})

test('legacy models keep their scalar price when no size map is configured', () => {
  assert.equal(modelCreditCost({ ...model, credit_cost_by_size: {} }, '2048x2048'), 5)
})
