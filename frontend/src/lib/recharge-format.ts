export function money(fen: number): string {
  return `¥${Math.floor(fen / 100)}.${String(fen % 100).padStart(2, '0')}`
}

export function yuanToFen(value: string): number | null {
  if (!/^(?:0|[1-9]\d{0,4})(?:\.\d{1,2})?$/.test(value)) return null
  const [whole = '0', fraction = ''] = value.split('.')
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
  return amount > 0 && amount <= 1_000_000 ? amount : null
}

export function rechargeStatus(order: { status: string; expired: boolean }): string {
  return order.status === 'paid' ? '已到账' : order.expired ? '支付链接已过期' : '待支付'
}
