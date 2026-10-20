<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Check, RefreshCw, Wallet } from 'lucide-vue-next'
import { authState, fetchCurrentUser } from '@/lib/auth'
import { ApiError } from '@/lib/api'
import { rechargeApi, type Checkout, type RechargeIntent, type RechargeOrder, type RechargePackage } from '@/lib/recharge'
import { money, rechargeStatus } from '@/lib/recharge-format'
import { randomId } from '@/lib/browser-crypto'

const route = useRoute()
const router = useRouter()
const enabled = ref(false)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const packages = ref<RechargePackage[]>([])
const selected = ref('')
const method = ref<'alipay' | 'wxpay'>('alipay')
const paymentMethods = ref<string[]>([])
const checkout = ref<Checkout | null>(null)
const returnedOrder = ref<RechargeOrder | null>(null)
const orders = ref<RechargeOrder[]>([])
const total = ref(0)
const page = ref(1)
const pendingIntent = ref<RechargeIntent | null>(null)
const owner = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let mounted = true
const currentSession = (session: string | null) => mounted && session === authState.sessionId
const selectedPackage = computed(() => packages.value.find(p => p.id === selected.value))
const activeOrder = computed(() => returnedOrder.value ?? checkout.value?.order ?? null)
const intentKey = () => `easy-painter:recharge-intent:${owner.value}`
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })

function saveIntent(intent: RechargeIntent | null) {
  if (intent) localStorage.setItem(intentKey(), JSON.stringify(intent))
  else localStorage.removeItem(intentKey())
  pendingIntent.value = intent
}

async function loadOrders(next = page.value) {
  const session = authState.sessionId
  const data = await rechargeApi.orders(next)
  if (!currentSession(session)) return
  orders.value = data.items
  total.value = data.total
  page.value = next
}

async function confirmPackage() {
  const pack = selectedPackage.value
  if (!pendingIntent.value && !pack) return
  busy.value = true
  error.value = ''
  const session = authState.sessionId
  try {
    const intent = pendingIntent.value ?? { key: randomId(), package_id: pack!.id, package_revision: pack!.revision, payment_method: method.value }
    saveIntent(intent)
    const result = await rechargeApi.create(intent)
    if (!currentSession(session)) return
    checkout.value = result
    returnedOrder.value = null
    saveIntent(null)
    await loadOrders(1)
    if (result.order.status === 'paid') await fetchCurrentUser()
  } catch (e) {
    if (currentSession(session)) {
      error.value = e instanceof Error ? e.message : '订单确认失败，请重试。'
      if (e instanceof ApiError && [400, 409, 422, 429].includes(e.status)) {
        saveIntent(null)
        const data = await rechargeApi.catalog()
        if (!currentSession(session)) return
        packages.value = data.packages
        enabled.value = data.enabled
        paymentMethods.value = data.payment_methods
        if (!paymentMethods.value.includes(method.value)) method.value = paymentMethods.value.includes('alipay') ? 'alipay' : 'wxpay'
      }
    }
  } finally {
    busy.value = false
  }
}

function pay() {
  const value = checkout.value
  if (!value?.action || !value.fields || value.order.status === 'paid' || value.order.expired) return
  const action = new URL(value.action)
  if (action.protocol !== 'https:' || action.username || action.password || action.pathname !== '/submit.php') {
    error.value = '支付暂时不可用，请联系管理员。'
    return
  }
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = action.href
  for (const [name, fieldValue] of Object.entries(value.fields)) {
    const input = document.createElement('input')
    input.type = 'hidden'; input.name = name; input.value = fieldValue
    form.appendChild(input)
  }
  document.body.appendChild(form)
  form.submit()
  form.remove()
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
    if (checkout.value?.order.id === id) checkout.value = { ...checkout.value, order }
    await loadOrders()
    if (order.status === 'paid') await fetchCurrentUser()
  } catch (e) {
    if (currentSession(session)) error.value = e instanceof Error ? e.message : '暂时无法确认，请勿重复付款。'
  } finally { busy.value = false }
}

function selectAnother() {
  checkout.value = null
  returnedOrder.value = null
  void router.replace('/recharge')
}

async function resumeOrder(id: string) {
  busy.value = true; error.value = ''
  const session = authState.sessionId
  try {
    const result = await rechargeApi.checkout(id)
    if (!currentSession(session)) return
    checkout.value = result; returnedOrder.value = null
    window.scrollTo({ top: 0, behavior: 'instant' })
  } catch (e) { if (currentSession(session)) error.value = e instanceof Error ? e.message : '订单暂时无法打开。' }
  finally { busy.value = false }
}

onMounted(async () => {
  const session = authState.sessionId
  try {
    await fetchCurrentUser()
    if (!currentSession(session)) return
    owner.value = authState.user?.id ?? ''
    if (!owner.value) { error.value = '账号信息暂时无法加载，请稍后重试。'; return }
    try {
      const saved = JSON.parse(localStorage.getItem(intentKey()) ?? 'null') as RechargeIntent | null
      if (saved?.key && saved.package_id && Number.isInteger(saved.package_revision) && ['alipay', 'wxpay'].includes(saved.payment_method)) pendingIntent.value = saved
    } catch { /* A malformed local draft cannot initiate payment. */ }
    const data = await rechargeApi.catalog()
    if (!currentSession(session)) return
    enabled.value = data.enabled
    paymentMethods.value = data.payment_methods
    if (!paymentMethods.value.includes(method.value)) method.value = paymentMethods.value.includes('alipay') ? 'alipay' : 'wxpay'
    packages.value = data.packages
    selected.value = data.packages[0]?.id ?? ''
    await loadOrders(1)
    if (!currentSession(session)) return
    const id = route.query.out_trade_no
    if (route.path === '/recharge/return' && typeof id === 'string' && /^\d{30}$/.test(id)) {
      const result = await rechargeApi.order(id)
      if (!currentSession(session)) return
      returnedOrder.value = result
      if (result.status !== 'paid') await refreshOrder(id)
    }
    if (!currentSession(session)) return
    timer = setInterval(() => {
      if (!document.hidden && activeOrder.value?.status === 'pending') void refreshOrder(activeOrder.value.id, false)
    }, 5000)
  } catch (e) { error.value = e instanceof Error ? e.message : '充值信息加载失败。' }
  finally { loading.value = false }
})

watch(() => authState.sessionId, () => {
  checkout.value = null; returnedOrder.value = null; orders.value = []; owner.value = ''; pendingIntent.value = null
  if (timer) clearInterval(timer)
  void router.replace('/login?redirect=/recharge')
})
onBeforeUnmount(() => { mounted = false; if (timer) clearInterval(timer) })
</script>

<template>
  <div class="recharge-page">
    <header class="recharge-heading">
      <div><p class="recharge-kicker">Credits</p><h1>充值中心</h1><p>为下一次灵感，添一点丝线。</p></div>
      <router-link to="/profile" class="recharge-balance"><Wallet :size="18" /><span>当前余额<strong>{{ authState.user?.credits ?? 0 }} <small>丝</small></strong></span></router-link>
    </header>

    <p v-if="loading" class="recharge-message">正在加载充值信息…</p>
    <p v-if="error" class="recharge-message recharge-error" role="alert">{{ error }}</p>
    <p v-if="!loading && !enabled" class="recharge-message">在线充值暂未开放，已有订单仍可查看和确认到账。</p>

    <section v-if="activeOrder" class="recharge-panel recharge-confirm" aria-label="充值订单">
      <div><span class="recharge-status" :class="{ paid: activeOrder.status === 'paid' }"><Check v-if="activeOrder.status === 'paid'" :size="16" />{{ rechargeStatus(activeOrder) }}</span><h2>{{ activeOrder.status === 'paid' ? '丝线已到账' : '确认这笔充值' }}</h2><p>{{ activeOrder.package_name }}</p></div>
      <dl class="recharge-summary"><div><dt>支付金额</dt><dd>{{ money(activeOrder.amount_fen) }}</dd></div><div><dt>付费丝线</dt><dd>{{ activeOrder.paid_credits }} 丝</dd></div><div v-if="activeOrder.gift_credits"><dt>额外赠送</dt><dd>{{ activeOrder.gift_credits }} 丝</dd></div><div><dt>支付方式</dt><dd>{{ activeOrder.payment_method === 'alipay' ? '支付宝' : '微信支付' }}</dd></div></dl>
      <p class="recharge-order-id">订单号 {{ activeOrder.id }}</p>
      <div class="recharge-actions"><button v-if="checkout?.action && enabled && activeOrder.status === 'pending' && !activeOrder.expired" class="primary-button" @click="pay">确认并支付 {{ money(activeOrder.amount_fen) }} <ArrowRight :size="16" /></button><button v-if="activeOrder.status === 'pending'" class="secondary-button" :disabled="busy" @click="refreshOrder(activeOrder.id)"><RefreshCw :size="15" />{{ busy ? '确认中…' : '我已支付，确认到账' }}</button><button class="ghost-button" @click="selectAnother">{{ activeOrder.status === 'paid' ? '继续充值' : '返回套餐' }}</button></div>
      <p v-if="activeOrder.status === 'pending'" class="recharge-note">支付结果未确认前，请勿重复付款。链接过期后完成的付款也会核实入账。</p>
    </section>

    <section v-else-if="!loading && enabled" class="recharge-panel">
      <h2>选择充值套餐</h2>
      <div v-if="packages.length" class="recharge-packages">
        <button v-for="pack in packages" :key="pack.id" class="recharge-package" :class="{ selected: selected === pack.id }" :aria-pressed="selected === pack.id" :disabled="Boolean(pendingIntent)" @click="selected = pack.id">
          <span class="recharge-package-name">{{ pack.name }}<Check v-if="selected === pack.id" :size="17" /></span><strong>{{ pack.paid_credits }} <small>丝</small></strong><span v-if="pack.gift_credits" class="recharge-gift">另赠 {{ pack.gift_credits }} 丝</span><span class="recharge-price">{{ money(pack.price_fen) }}</span>
        </button>
      </div>
      <p v-else class="recharge-note">暂时没有可购买的套餐。</p>
      <fieldset v-if="packages.length" class="recharge-methods"><legend>支付方式</legend><label v-if="paymentMethods.includes('alipay')"><input v-model="method" type="radio" value="alipay" :disabled="Boolean(pendingIntent)" />支付宝</label><label v-if="paymentMethods.includes('wxpay')"><input v-model="method" type="radio" value="wxpay" :disabled="Boolean(pendingIntent)" />微信支付</label></fieldset>
      <p v-if="pendingIntent" class="recharge-note">上次订单请求尚未确认，将使用同一请求继续核实，不会重复创建。</p>
      <button v-if="packages.length || pendingIntent" class="primary-button" :disabled="busy || (!selectedPackage && !pendingIntent)" @click="confirmPackage">{{ busy ? '确认中…' : pendingIntent ? '继续确认上次订单' : '确认套餐' }}<ArrowRight :size="16" /></button>
      <p class="recharge-note">充值到账后即可用于站内创作。</p>
    </section>

    <section class="recharge-panel recharge-history"><div class="recharge-section-heading"><h2>充值记录</h2><button class="ghost-button" :disabled="busy" @click="loadOrders()">刷新记录</button></div>
      <p v-if="!orders.length" class="recharge-note">还没有充值记录。</p>
      <div v-else class="recharge-table-wrap"><table><thead><tr><th>订单 / 时间</th><th>充值内容</th><th>金额</th><th>状态</th><th></th></tr></thead><tbody><tr v-for="order in orders" :key="order.id"><td><code>{{ order.id }}</code><small>{{ date(order.created_at) }}</small></td><td>{{ order.paid_credits }} 丝<span v-if="order.gift_credits"> + {{ order.gift_credits }} 赠送</span></td><td>{{ money(order.amount_fen) }}</td><td>{{ rechargeStatus(order) }}</td><td><button v-if="enabled && order.status === 'pending' && !order.expired" class="ghost-button" :disabled="busy" @click="resumeOrder(order.id)">继续支付</button><button v-if="order.status === 'pending'" class="ghost-button" :disabled="busy" @click="refreshOrder(order.id)">确认到账</button></td></tr></tbody></table></div>
      <div v-if="total > 20" class="recharge-pagination"><button class="ghost-button" :disabled="page <= 1" @click="loadOrders(page - 1)">上一页</button><span>{{ page }} / {{ Math.ceil(total / 20) }}</span><button class="ghost-button" :disabled="page * 20 >= total" @click="loadOrders(page + 1)">下一页</button></div>
    </section>
  </div>
</template>

<style scoped>
.recharge-page{max-width:1000px;margin:32px auto 80px;display:grid;gap:24px}.recharge-heading,.recharge-section-heading{display:flex;align-items:center;justify-content:space-between;gap:24px}.recharge-kicker{font-family:var(--font-mono);text-transform:uppercase;font-size:11px;letter-spacing:.15em;color:var(--accent);margin:0 0 8px}.recharge-heading h1{font-family:var(--font-display);font-size:32px;font-weight:500;margin:0 0 8px}.recharge-heading p:not(.recharge-kicker){color:var(--text-secondary);margin:0}.recharge-balance{display:flex;align-items:center;gap:14px;color:var(--text-secondary);text-decoration:none;font-size:12px}.recharge-balance strong{display:block;color:var(--text-primary);font-family:var(--font-mono);font-size:28px;margin-top:4px}.recharge-balance small{font:14px var(--font-body)}.recharge-panel{padding:28px;border:1px solid var(--border);border-radius:12px;background:var(--bg-surface)}h2{font-size:18px;font-weight:500;margin:0 0 20px}.recharge-packages{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:28px}.recharge-package{display:flex;flex-direction:column;align-items:flex-start;gap:12px;min-height:185px;padding:22px;border:1px solid var(--border);border-radius:8px;background:var(--bg-input);color:var(--text-primary);cursor:pointer;text-align:left}.recharge-package.selected{border-color:var(--accent);background:var(--accent-soft)}.recharge-package-name{display:flex;justify-content:space-between;align-items:center;width:100%;color:var(--text-secondary);font-size:13px}.recharge-package strong{font:32px var(--font-mono)}.recharge-package strong small{font:14px var(--font-body)}.recharge-gift{font-size:12px;color:var(--accent)}.recharge-price{margin-top:auto;font:18px var(--font-mono)}.recharge-methods{display:flex;gap:24px;border:0;padding:0;margin:0 0 24px}.recharge-methods legend{margin-bottom:12px;color:var(--text-secondary);font-size:13px}.recharge-methods label{display:flex;gap:8px;align-items:center;font-size:14px}.recharge-methods input{accent-color:var(--accent)}.recharge-note{font-size:13px;color:var(--text-muted);line-height:1.7;margin:16px 0 0}.recharge-message{padding:16px 20px;background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;line-height:1.6;margin:0}.recharge-error{color:var(--error);background:var(--error-soft)}.recharge-status{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:var(--accent);margin-bottom:16px}.recharge-status.paid{color:var(--success)}.recharge-confirm h2{font-size:24px;margin:0 0 8px}.recharge-confirm p{color:var(--text-secondary)}.recharge-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;padding:24px 0;margin:16px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}.recharge-summary dt{font-size:12px;color:var(--text-muted);margin-bottom:8px}.recharge-summary dd{margin:0;font-size:18px}.recharge-order-id{font:12px var(--font-mono);overflow-wrap:anywhere}.recharge-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:24px}.primary-button,.secondary-button{display:inline-flex;align-items:center;justify-content:center;gap:10px}.recharge-section-heading h2{margin:0}.recharge-table-wrap{overflow:auto;margin-top:16px}.recharge-history table{width:100%;border-collapse:collapse;text-align:left;font-size:13px;white-space:nowrap}.recharge-history th{font-weight:400;color:var(--text-muted)}.recharge-history th,.recharge-history td{padding:16px 12px;border-bottom:1px solid var(--border)}.recharge-history td:first-child{padding-left:0}.recharge-history code{font-size:11px}.recharge-history td small{display:block;color:var(--text-muted);margin-top:5px}.recharge-pagination{display:flex;justify-content:flex-end;align-items:center;gap:12px;margin-top:16px;font-size:13px}@media(max-width:700px){.recharge-page{margin-top:16px;gap:16px}.recharge-panel{padding:20px}.recharge-heading{align-items:flex-start;gap:12px}.recharge-heading h1{font-size:26px}.recharge-heading p:not(.recharge-kicker){font-size:13px}.recharge-balance{gap:8px}.recharge-balance strong{font-size:22px}.recharge-packages{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.recharge-package{padding:16px}.recharge-summary{grid-template-columns:repeat(2,1fr)}}@media(prefers-reduced-motion:no-preference){.recharge-package{transition:border-color 220ms cubic-bezier(0,0,.2,1),background 220ms cubic-bezier(0,0,.2,1)}}
</style>
