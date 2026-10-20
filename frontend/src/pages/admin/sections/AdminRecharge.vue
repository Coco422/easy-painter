<script setup lang="ts">
import { h, onMounted, reactive, ref } from 'vue'
import { NAlert, NButton, NCard, NCheckbox, NCheckboxGroup, NDataTable, NForm, NFormItem, NInput, NInputNumber, NModal, NPagination, NSpace, NSwitch, NTag, useMessage, type DataTableColumns } from 'naive-ui'
import { ApiError } from '@/lib/api'
import { rechargeApi, type AdminRechargeOrder, type RechargeConfig, type RechargePackage } from '@/lib/recharge'
import { money, rechargeStatus, yuanToFen } from '@/lib/recharge-format'

const emit = defineEmits<{ 'auth-expired': [] }>()
const message = useMessage()
const config = ref<RechargeConfig>({ enabled: false, configured: false, packages: [], revision: 0,
  gateway_url: 'https://zpayz.cn', merchant_id: '', public_base_url: '', payment_methods: ['alipay'],
  key_configured: false, encryption_ready: false, configuration_error: false })
const savingConfig = ref(false)
const configLoaded = ref(false)
const paymentForm = reactive({ enabled: false, gateway_url: 'https://zpayz.cn', merchant_id: '', merchant_key: '',
  public_base_url: window.location.origin, payment_methods: ['alipay'] as ('alipay' | 'wxpay')[] })
const orders = ref<AdminRechargeOrder[]>([])
const loading = ref(false)
const saving = ref(false)
const modal = ref(false)
const editing = ref<RechargePackage | null>(null)
const page = ref(1)
const total = ref(0)
const form = reactive({ name: '', price: '10.00', paid_credits: 100, gift_credits: 0, is_enabled: false, sort_order: 0 })

function handleError(e: unknown) {
  if (e instanceof ApiError && e.status === 401) { emit('auth-expired'); return }
  message.error(e instanceof Error ? e.message : '操作失败，请重试。')
}
async function load() {
  loading.value = true
  try {
    const [settings, data] = await Promise.all([rechargeApi.adminConfig(), rechargeApi.adminOrders(page.value)])
    config.value = settings; orders.value = data.items; total.value = data.total
    if (!configLoaded.value) {
      Object.assign(paymentForm, { enabled: settings.enabled, gateway_url: settings.gateway_url,
        merchant_id: settings.merchant_id, public_base_url: settings.public_base_url || window.location.origin,
        payment_methods: settings.revision ? [...settings.payment_methods] : ['alipay'], merchant_key: '' })
      configLoaded.value = true
    }
  } catch (e) { handleError(e) }
  finally { loading.value = false }
}
async function savePaymentConfig() {
  if (!paymentForm.merchant_id.trim() || !paymentForm.public_base_url.trim() || !paymentForm.payment_methods.length) {
    message.error('请填写商户 ID、网站公网地址，并选择已开通的支付方式。'); return
  }
  savingConfig.value = true
  try {
    config.value = await rechargeApi.adminSaveConfig({ ...paymentForm, expected_revision: config.value.revision,
      gateway_url: paymentForm.gateway_url.trim(), merchant_id: paymentForm.merchant_id.trim(),
      public_base_url: paymentForm.public_base_url.trim() })
    paymentForm.merchant_key = ''
    message.success('支付配置已加密保存并即时生效。')
  } catch (e) { handleError(e) }
  finally { savingConfig.value = false }
}
function edit(pack?: RechargePackage) {
  editing.value = pack ?? null
  Object.assign(form, pack ? { ...pack, price: (pack.price_fen / 100).toFixed(2) } : { name: '灵感丝线 100 丝', price: '10.00', paid_credits: 100, gift_credits: 0, is_enabled: false, sort_order: 0 })
  modal.value = true
}
async function save() {
  const fen = yuanToFen(form.price)
  if (fen === null || !form.name.trim() || /[&=\r\n\t]/.test(form.name) || !Number.isInteger(form.paid_credits) || form.paid_credits < 1 || !Number.isInteger(form.gift_credits) || form.gift_credits < 0 || !Number.isInteger(form.sort_order) || form.sort_order < 0) {
    message.error('请填写有效名称、金额（最多两位小数）、付费丝和赠送丝数量。'); return
  }
  saving.value = true
  try {
    const body = { name: form.name.trim(), price_fen: fen, paid_credits: form.paid_credits, gift_credits: form.gift_credits, is_enabled: form.is_enabled, sort_order: form.sort_order }
    if (editing.value) await rechargeApi.adminUpdatePackage(editing.value.id, body, editing.value.revision)
    else await rechargeApi.adminCreatePackage(body)
    modal.value = false; message.success('套餐已保存，仅影响新订单。'); await load()
  } catch (e) { handleError(e) }
  finally { saving.value = false }
}
async function check(id: string) {
  try { const result = await rechargeApi.adminRefresh(id); message.info(rechargeStatus(result)); await load() }
  catch (e) { handleError(e) }
}
const packageColumns: DataTableColumns<RechargePackage> = [
  { title: '套餐', key: 'name', minWidth: 160 },
  { title: '价格', key: 'price_fen', render: row => money(row.price_fen) },
  { title: '付费丝', key: 'paid_credits' }, { title: '赠送丝', key: 'gift_credits' },
  { title: '排序', key: 'sort_order' },
  { title: '状态', key: 'is_enabled', render: row => h(NTag, { type: row.is_enabled ? 'success' : 'default', size: 'small' }, { default: () => row.is_enabled ? '已上架' : '已停用' }) },
  { title: '操作', key: 'actions', render: row => h(NButton, { size: 'small', onClick: () => edit(row) }, { default: () => '编辑' }) },
]
const orderColumns: DataTableColumns<AdminRechargeOrder> = [
  { title: '订单号', key: 'id', minWidth: 230 }, { title: '用户', key: 'username', minWidth: 120 },
  { title: '套餐', key: 'package_name', minWidth: 140 },
  { title: '金额', key: 'amount_fen', render: row => money(row.amount_fen) },
  { title: '付费 / 赠送丝', key: 'credits', render: row => `${row.paid_credits} / ${row.gift_credits}` },
  { title: '状态', key: 'status', render: row => rechargeStatus(row) },
  { title: '创建时间（北京）', key: 'created_at', minWidth: 170, render: row => new Date(row.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) },
  { title: '平台流水号', key: 'provider_trade_no', minWidth: 180, render: row => row.provider_trade_no ?? '—' },
  { title: '查单提示', key: 'last_check_error', minWidth: 130, render: row => row.last_check_error ? '尚未确认，可重试' : '—' },
  { title: '操作', key: 'actions', width: 100, render: row => row.status === 'pending' ? h(NButton, { size: 'small', onClick: () => check(row.id) }, { default: () => '核实到账' }) : '—' },
]
onMounted(load)
</script>

<template>
  <div class="admin-recharge">
    <NAlert :type="config.enabled && config.configured ? 'success' : 'warning'" title="在线收款状态">
      {{ !config.configured ? 'ZPAY 商户配置尚未完成。套餐可先编辑，用户暂时无法付款。' : config.enabled ? '收款已开放，用户可购买已上架套餐。' : '商户已配置，在线收款保持关闭；已有订单仍会核实入账。' }}
      请先保存支付配置，再开启在线收款并上架套餐。
    </NAlert>
    <NAlert v-if="config.configuration_error" type="error" title="已保存配置暂时无法解密">请联系运维核对服务器加密主密钥；不要直接更换主密钥或删除历史配置。</NAlert>
    <NCard title="ZPAY 支付配置" size="small">
      <NAlert v-if="!config.encryption_ready" type="warning" :show-icon="false">服务器加密尚未就绪，请联系运维完成初始化后刷新。</NAlert>
      <NForm label-placement="top" class="payment-config-form" :disabled="savingConfig || !configLoaded" @submit.prevent="savePaymentConfig">
        <div class="recharge-admin-fields">
          <NFormItem label="商户 ID（PID）"><NInput v-model:value="paymentForm.merchant_id" placeholder="填写 ZPAY 商户 ID" autocomplete="off" /></NFormItem>
          <NFormItem label="商户密钥（KEY）"><NInput v-model:value="paymentForm.merchant_key" type="password" :placeholder="config.key_configured ? '已保存；留空保留，填写则替换' : '填写 ZPAY 商户密钥'" autocomplete="new-password" /></NFormItem>
        </div>
        <div class="recharge-admin-fields">
          <NFormItem label="支付网关根地址"><NInput v-model:value="paymentForm.gateway_url" placeholder="https://zpayz.cn" /></NFormItem>
          <NFormItem label="网站公网地址"><NInput v-model:value="paymentForm.public_base_url" placeholder="https://app.example.com" /></NFormItem>
        </div>
        <NFormItem label="已开通的支付方式"><NCheckboxGroup v-model:value="paymentForm.payment_methods"><NSpace><NCheckbox value="alipay" label="支付宝" /><NCheckbox value="wxpay" label="微信支付" /></NSpace></NCheckboxGroup></NFormItem>
        <NFormItem label="开放在线收款"><NSwitch v-model:value="paymentForm.enabled" /></NFormItem>
        <p class="payment-config-note">密钥加密保存，保存后不回显。只勾选已在 ZPAY 开通的支付方式。配置修改即时生效，已有订单仍按原商户信息核实。</p>
        <NSpace justify="end"><NButton type="primary" :loading="savingConfig" :disabled="!configLoaded || !config.encryption_ready" @click="savePaymentConfig">保存支付配置</NButton></NSpace>
      </NForm>
    </NCard>
    <NCard title="充值套餐" size="small"><template #header-extra><NButton type="primary" @click="edit()">新增套餐</NButton></template>
      <NDataTable :columns="packageColumns" :data="config.packages" :loading="loading" :scroll-x="750" :bordered="false" />
    </NCard>
    <NCard title="充值订单" size="small"><template #header-extra><NButton :loading="loading" @click="load">刷新</NButton></template>
      <NDataTable :columns="orderColumns" :data="orders" :loading="loading" :scroll-x="1450" :bordered="false" />
      <NPagination v-if="total > 20" v-model:page="page" :item-count="total" :page-size="20" class="recharge-admin-pagination" @update:page="load" />
    </NCard>
    <NModal v-model:show="modal" preset="card" :title="editing ? '编辑充值套餐' : '新增充值套餐'" style="max-width:520px" :mask-closable="!saving" :close-on-esc="!saving">
      <NForm label-placement="top" @submit.prevent="save">
        <NFormItem label="套餐名称"><NInput v-model:value="form.name" maxlength="80" /></NFormItem>
        <div class="recharge-admin-fields"><NFormItem label="价格（元）"><NInput v-model:value="form.price" placeholder="10.00" /></NFormItem><NFormItem label="排序"><NInputNumber v-model:value="form.sort_order" :min="0" :max="10000" :precision="0" /></NFormItem></div>
        <div class="recharge-admin-fields"><NFormItem label="付费丝"><NInputNumber v-model:value="form.paid_credits" :min="1" :max="10000000" :precision="0" /></NFormItem><NFormItem label="额外赠送丝"><NInputNumber v-model:value="form.gift_credits" :min="0" :max="10000000" :precision="0" /></NFormItem></div>
        <NFormItem label="上架套餐"><NSwitch v-model:value="form.is_enabled" /></NFormItem>
        <NAlert type="info" :show-icon="false">修改只影响新订单。付费丝与赠送丝分开记录，为之后的消费返佣保留实付依据。</NAlert>
        <NSpace justify="end" style="margin-top:20px"><NButton :disabled="saving" @click="modal = false">取消</NButton><NButton type="primary" :loading="saving" @click="save">保存套餐</NButton></NSpace>
      </NForm>
    </NModal>
  </div>
</template>

<style scoped>
.admin-recharge{display:grid;grid-template-columns:minmax(0,1fr);min-width:0;gap:24px}.admin-recharge :deep(.n-card){min-width:0}.recharge-admin-fields{display:grid;grid-template-columns:1fr 1fr;gap:24px}.recharge-admin-pagination{justify-content:flex-end;margin-top:20px}.payment-config-form{margin-top:16px}.payment-config-note{font-size:13px;color:var(--text-secondary);line-height:1.6;margin:0 0 16px}@media(max-width:768px){.recharge-admin-fields{grid-template-columns:1fr;gap:0}}
</style>
