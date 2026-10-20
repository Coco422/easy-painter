import { apiRequest, adminApiRequest } from './api'
import type { PageResponse } from './types'

export interface RechargePackage {
  id: string; name: string; price_fen: number; paid_credits: number; gift_credits: number
  is_enabled: boolean; sort_order: number; revision: number
}
export interface RechargeOrder {
  id: string; package_name: string; amount_fen: number; paid_credits: number; gift_credits: number
  payment_method: string; status: 'pending' | 'paid'; expired: boolean
  created_at: string; expires_at: string; paid_at: string | null
}
export interface RechargeIntent { key: string; package_id: string; package_revision: number; payment_method: 'alipay' | 'wxpay' }
export interface Checkout { order: RechargeOrder; action: string | null; fields: Record<string, string> | null }
export type AdminRechargeOrder = RechargeOrder & { user_id: string; username: string; provider_trade_no: string | null; last_check_error: string | null }
export interface PaymentConfigInput {
  expected_revision: number; enabled: boolean; gateway_url: string; merchant_id: string
  merchant_key: string; public_base_url: string; payment_methods: ('alipay' | 'wxpay')[]
}
export interface RechargeConfig {
  enabled: boolean; configured: boolean; packages: RechargePackage[]; revision: number
  gateway_url: string; merchant_id: string; public_base_url: string; payment_methods: ('alipay' | 'wxpay')[]
  key_configured: boolean; encryption_ready: boolean; configuration_error: boolean
}
export type PackageInput = Omit<RechargePackage, 'id' | 'revision'>

export const rechargeApi = {
  catalog: () => apiRequest<{ enabled: boolean; payment_methods: string[]; packages: RechargePackage[] }>('/api/v1/recharge/catalog'),
  orders: (page = 1) => apiRequest<PageResponse<RechargeOrder>>(`/api/v1/recharge/orders?page=${page}`),
  order: (id: string) => apiRequest<RechargeOrder>(`/api/v1/recharge/orders/${encodeURIComponent(id)}`),
  create: (intent: RechargeIntent) => apiRequest<Checkout>('/api/v1/recharge/orders', {
    method: 'POST', headers: { 'Idempotency-Key': intent.key },
    body: JSON.stringify({ package_id: intent.package_id, package_revision: intent.package_revision, payment_method: intent.payment_method }),
  }),
  refresh: (id: string) => apiRequest<RechargeOrder>(`/api/v1/recharge/orders/${encodeURIComponent(id)}/refresh`, { method: 'POST' }),
  checkout: (id: string) => apiRequest<Checkout>(`/api/v1/recharge/orders/${encodeURIComponent(id)}/checkout`, { method: 'POST' }),
  adminConfig: () => adminApiRequest<RechargeConfig>('/api/v1/admin/recharge/config'),
  adminSaveConfig: (body: PaymentConfigInput) => adminApiRequest<RechargeConfig>('/api/v1/admin/recharge/config', { method: 'PUT', body: JSON.stringify(body) }),
  adminOrders: (page = 1) => adminApiRequest<PageResponse<AdminRechargeOrder>>(`/api/v1/admin/recharge/orders?page=${page}`),
  adminCreatePackage: (body: PackageInput) => adminApiRequest<RechargePackage>('/api/v1/admin/recharge/packages', { method: 'POST', body: JSON.stringify(body) }),
  adminUpdatePackage: (id: string, body: PackageInput, revision: number) => adminApiRequest<RechargePackage>(`/api/v1/admin/recharge/packages/${encodeURIComponent(id)}`, {
    method: 'PUT', body: JSON.stringify({ ...body, expected_revision: revision }),
  }),
  adminRefresh: (id: string) => adminApiRequest<RechargeOrder>(`/api/v1/admin/recharge/orders/${encodeURIComponent(id)}/refresh`, { method: 'POST' }),
}
