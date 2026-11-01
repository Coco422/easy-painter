<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshCw, Wallet } from 'lucide-vue-next'
import { authState, fetchCurrentUser } from '@/lib/auth'
import { rechargeApi, type RechargeOrder } from '@/lib/recharge'
import { money, rechargeStatus } from '@/lib/recharge-format'

// Keep payment returns and reconciliation available for historical orders.
// New credit is obtained through the redemption form in the profile.
const route = useRoute()
const router = useRouter()
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const returnedOrder = ref<RechargeOrder | null>(null)
const orders = ref<RechargeOrder[]>([])
const total = ref(0)
const page = ref(1)
let mounted = true
let timer: ReturnType<typeof setInterval> | undefined
const currentSession = (session: string | null) => mounted && session === authState.sessionId
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })

async function loadOrders(next = page.value) {
  const session = authState.sessionId
  try {
    const data = await rechargeApi.orders(next)
    if (!currentSession(session)) return
    orders.value = data.items
    total.value = data.total
    page.value = next
  } catch (e) {
    if (currentSession(session)) error.value = e instanceof Error ? e.message : '订单记录加载失败。'
  }
}

async function refreshOrder(id: string, remote = true) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  const session = authState.sessionId
  try {
    const order = await (remote ? rechargeApi.refresh(id) : rechargeApi.order(id))
    if (!currentSession(session)) return
    if (returnedOrder.value?.id === id) returnedOrder.value = order
    await loadOrders()
    if (order.status === 'paid' && currentSession(session)) await fetchCurrentUser()
  } catch (e) {
    if (currentSession(session)) error.value = e instanceof Error ? e.message : '暂时无法确认，请勿重复付款。'
  } finally { busy.value = false }
}

onMounted(async () => {
  const session = authState.sessionId
  try {
    await fetchCurrentUser()
    if (!currentSession(session)) return
    await loadOrders(1)
    if (!currentSession(session)) return
    const id = route.query.out_trade_no
    if (typeof id === 'string' && /^\d{30}$/.test(id)) {
      const order = await rechargeApi.order(id)
      if (!currentSession(session)) return
      returnedOrder.value = order
      if (order.status !== 'paid') await refreshOrder(id)
    }
    if (!currentSession(session)) return
    timer = setInterval(() => {
      if (!document.hidden && returnedOrder.value?.status === 'pending') void refreshOrder(returnedOrder.value.id, false)
    }, 5000)
  } catch (e) {
    if (currentSession(session)) error.value = e instanceof Error ? e.message : '订单信息加载失败。'
  } finally { loading.value = false }
})

watch(() => authState.sessionId, () => {
  returnedOrder.value = null
  orders.value = []
  if (timer) clearInterval(timer)
  void router.replace({ path: '/login', query: { redirect: route.fullPath } })
})
onBeforeUnmount(() => { mounted = false; if (timer) clearInterval(timer) })
</script>

<template>
  <div class="recharge-page">
    <header class="recharge-heading">
      <div><p class="recharge-kicker">Orders</p><h1>历史订单</h1><p>查看既有订单的到账状态。</p></div>
      <router-link to="/profile#redeem" class="recharge-balance"><Wallet :size="18" /><span>兑换卡入账<strong>{{ authState.user?.credits ?? 0 }} <small>丝</small></strong></span></router-link>
    </header>
    <p v-if="loading" class="recharge-message">正在加载订单信息…</p>
    <p v-if="error" class="recharge-message recharge-error" role="alert">{{ error }}</p>
    <section v-if="returnedOrder" class="recharge-panel recharge-confirm" aria-label="历史订单">
      <h2>{{ rechargeStatus(returnedOrder) }}</h2><p>{{ returnedOrder.package_name }}</p>
      <p class="recharge-order-id">订单号 {{ returnedOrder.id }}</p>
      <p>支付金额 {{ money(returnedOrder.amount_fen) }}</p>
      <button v-if="returnedOrder.status === 'pending'" class="secondary-button" :disabled="busy" @click="refreshOrder(returnedOrder.id)"><RefreshCw :size="15" />{{ busy ? '确认中…' : '我已支付，确认到账' }}</button>
      <p v-if="returnedOrder.status === 'pending'" class="recharge-note">支付结果未确认前，请勿重复付款。</p>
    </section>
    <section class="recharge-panel recharge-history">
      <div class="recharge-section-heading"><h2>订单记录</h2><button class="ghost-button" :disabled="busy" @click="loadOrders()">刷新记录</button></div>
      <p v-if="!orders.length" class="recharge-note">还没有订单记录。</p>
      <div v-else class="recharge-table-wrap"><table><thead><tr><th>订单 / 时间</th><th>内容</th><th>金额</th><th>状态</th><th></th></tr></thead><tbody><tr v-for="order in orders" :key="order.id"><td><code>{{ order.id }}</code><small>{{ date(order.created_at) }}</small></td><td>{{ order.paid_credits }} 丝<span v-if="order.gift_credits"> + {{ order.gift_credits }} 赠送</span></td><td>{{ money(order.amount_fen) }}</td><td>{{ rechargeStatus(order) }}</td><td><button v-if="order.status === 'pending'" class="ghost-button" :disabled="busy" @click="refreshOrder(order.id)">确认到账</button></td></tr></tbody></table></div>
      <div v-if="total > 20" class="recharge-pagination"><button class="ghost-button" :disabled="page <= 1" @click="loadOrders(page - 1)">上一页</button><span>{{ page }} / {{ Math.ceil(total / 20) }}</span><button class="ghost-button" :disabled="page * 20 >= total" @click="loadOrders(page + 1)">下一页</button></div>
    </section>
  </div>
</template>

<style scoped>
.recharge-page{max-width:1000px;margin:32px auto 80px;display:grid;gap:24px}.recharge-heading,.recharge-section-heading{display:flex;align-items:center;justify-content:space-between;gap:24px}.recharge-kicker{font-family:var(--font-mono);text-transform:uppercase;font-size:11px;letter-spacing:.15em;color:var(--accent);margin:0 0 8px}.recharge-heading h1{font-family:var(--font-display);font-size:32px;font-weight:500;margin:0 0 8px}.recharge-heading p:not(.recharge-kicker){color:var(--text-secondary);margin:0}.recharge-balance{display:flex;align-items:center;gap:14px;color:var(--text-secondary);text-decoration:none;font-size:12px}.recharge-balance strong{display:block;color:var(--text-primary);font-family:var(--font-mono);font-size:28px;margin-top:4px}.recharge-balance small{font:14px var(--font-body)}.recharge-panel{padding:28px;border:1px solid var(--border);border-radius:12px;background:var(--bg-surface)}h2{font-size:18px;font-weight:500;margin:0 0 20px}.recharge-packages{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:28px}.recharge-package{display:flex;flex-direction:column;align-items:flex-start;gap:12px;min-height:185px;padding:22px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);color:var(--text-primary);cursor:pointer;text-align:left}.recharge-package.selected{border-color:var(--accent);background:var(--accent-soft)}.recharge-package-name{display:flex;justify-content:space-between;align-items:center;width:100%;color:var(--text-secondary);font-size:13px}.recharge-package strong{font:32px var(--font-mono)}.recharge-package strong small{font:14px var(--font-body)}.recharge-gift{font-size:12px;color:var(--accent)}.recharge-price{margin-top:auto;font:18px var(--font-mono)}.recharge-methods{display:flex;gap:24px;border:0;padding:0;margin:0 0 24px}.recharge-methods legend{margin-bottom:12px;color:var(--text-secondary);font-size:13px}.recharge-methods label{display:flex;gap:8px;align-items:center;font-size:14px}.recharge-methods input{accent-color:var(--accent)}.recharge-note{font-size:13px;color:var(--text-muted);line-height:1.7;margin:16px 0 0}.recharge-message{padding:16px 20px;background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;line-height:1.6;margin:0}.recharge-error{color:var(--error);background:var(--error-soft)}.recharge-status{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:var(--accent);margin-bottom:16px}.recharge-status.paid{color:var(--success)}.recharge-confirm h2{font-size:24px;margin:0 0 8px}.recharge-confirm p{color:var(--text-secondary)}.recharge-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;padding:24px 0;margin:16px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}.recharge-summary dt{font-size:12px;color:var(--text-muted);margin-bottom:8px}.recharge-summary dd{margin:0;font-size:18px}.recharge-order-id{font:12px var(--font-mono);overflow-wrap:anywhere}.recharge-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:24px}.primary-button,.secondary-button{display:inline-flex;align-items:center;justify-content:center;gap:10px}.recharge-section-heading h2{margin:0}.recharge-table-wrap{overflow:auto;margin-top:16px}.recharge-history table{width:100%;border-collapse:collapse;text-align:left;font-size:13px;white-space:nowrap}.recharge-history th{font-weight:400;color:var(--text-muted)}.recharge-history th,.recharge-history td{padding:16px 12px;border-bottom:1px solid var(--border)}.recharge-history td:first-child{padding-left:0}.recharge-history code{font-size:11px}.recharge-history td small{display:block;color:var(--text-muted);margin-top:5px}.recharge-pagination{display:flex;justify-content:flex-end;align-items:center;gap:12px;margin-top:16px;font-size:13px}@media(max-width:700px){.recharge-page{margin-top:16px;gap:16px}.recharge-panel{padding:20px}.recharge-heading{align-items:flex-start;gap:12px}.recharge-heading h1{font-size:26px}.recharge-heading p:not(.recharge-kicker){font-size:13px}.recharge-balance{gap:8px}.recharge-balance strong{font-size:22px}.recharge-packages{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.recharge-package{padding:16px}.recharge-summary{grid-template-columns:repeat(2,1fr)}}@media(prefers-reduced-motion:no-preference){.recharge-package{transition:border-color 220ms cubic-bezier(0,0,.2,1),background 220ms cubic-bezier(0,0,.2,1)}}
</style>
