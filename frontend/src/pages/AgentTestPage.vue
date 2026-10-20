<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AgentToolError, callTool, mcpRpc } from '@/lib/agent'
import { randomId } from '@/lib/browser-crypto'
import { authState, fetchCurrentUser } from '@/lib/auth'
import './agent.css'
const route = useRoute(), router = useRouter()
const error = ref(''), ready = ref(false), busy = ref(false)
const models = ref<{ id:string; label:string; credit_cost:number }[]>([]), model = ref(''), prompt = ref('绘制一张清晰的实验工作流程图，展示采集、处理和分析三个步骤。')
const balance = ref<{ credits:number; max_per_job:number }>()
const result = ref<{ job_id:string; status:string; image_url?:string; billing_status?:string; prompt?:string; error_message?:string }>()
const pending = ref<{ request_id:string; prompt:string; model:string; size:string; max_cost:number }>()
const requestDone = ref(false)
let token = '', endpoint = '', disposed = false, timer:number | undefined
async function refresh() {
  if (!ready.value) return
  try { const next = await callTool(endpoint, token, 'get_balance'); if (disposed) return; balance.value = next; await fetchCurrentUser() }
  catch (e) { if (!disposed) error.value = (e as Error).message }
}
async function poll() {
  if (!result.value || disposed) return
  try {
    const next = await callTool(endpoint, token, 'get_job', { job_id:result.value.job_id })
    if (disposed) return
    result.value = next
    if (['queued','processing'].includes(next.status)) timer = window.setTimeout(poll, 3000)
    else { requestDone.value = true; await refresh() }
  } catch (e) { if (!disposed) error.value = (e as Error).message }
}
async function generate() {
  if (busy.value || requestDone.value) return
  busy.value = true; error.value = ''
  try {
    if (!pending.value) {
      const estimate = await callTool(endpoint, token, 'estimate_cost', { model:model.value, size:'auto' })
      if (disposed) return
      pending.value = { request_id:randomId(), prompt:prompt.value, model:model.value, size:'auto', max_cost:estimate.credit_cost }
    }
    const response = await callTool(endpoint, token, 'generate_image', pending.value)
    if (disposed) return
    result.value = { job_id:response.job_id, status:'queued' }
    pending.value = undefined
    await refresh(); await poll()
  } catch (e) {
    if (!disposed) {
      const rejected = e instanceof AgentToolError && [400,402,403,409,410,422,429].includes(e.status)
      if (rejected) pending.value = undefined
      error.value = (e as Error).message + (rejected ? '' : '。如提交结果未知，请用下方按钮确认原请求。')
    }
  }
  finally { if (!disposed) busy.value = false }
}
onMounted(async () => {
  busy.value = true
  try {
    const data = JSON.parse(sessionStorage.getItem('easy-painter:agent-test') ?? 'null')
    sessionStorage.removeItem('easy-painter:agent-test')
    if (!data || data.state !== route.query.state || !route.query.code || route.query.iss !== location.origin) throw new Error('授权未完成、已拒绝或测试状态已过期，请重新连接。')
    endpoint = data.endpoint
    const code = String(route.query.code)
    await router.replace('/mcp/callback')
    const response = await fetch('/api/oauth/token', { method:'POST', headers:{ 'Content-Type':'application/x-www-form-urlencoded' }, body:new URLSearchParams({ grant_type:'authorization_code', client_id:data.clientId, code, code_verifier:data.verifier, redirect_uri:data.redirect, resource:endpoint }) })
    const credentials = await response.json()
    if (!response.ok) throw new Error(credentials.error_description ?? '令牌交换失败。')
    token = credentials.access_token
    await mcpRpc(endpoint, token, 'initialize', { protocolVersion:'2025-11-25', capabilities:{}, clientInfo:{ name:'easy-painter-web-test',version:'1.0' } })
    const [list, account] = await Promise.all([callTool(endpoint,token,'list_models'),callTool(endpoint,token,'get_balance')])
    if (disposed) return
    models.value = list.models; model.value = models.value[0]?.id ?? ''; balance.value = account; ready.value = true
  } catch (e) { if (!disposed) error.value = (e as Error).message }
  finally { if (!disposed) busy.value = false }
})
watch(() => authState.sessionId, () => {
  disposed = true; token = ''; ready.value = false; pending.value = undefined; result.value = undefined; balance.value = undefined
  if (timer) clearTimeout(timer)
  void router.replace('/mcp')
})
onBeforeUnmount(() => { disposed = true; token = ''; if (timer) clearTimeout(timer) })
</script>
<template><main class="agent-page agent-consent"><header class="agent-heading"><p class="agent-eyebrow">MCP CONNECTION TEST</p><h1>{{ ready ? '连接成功，可以开始创作。' : error ? '连接未完成' : '正在验证连接…' }}</h1><p>这里直接调用真实 MCP 协议。页面刷新后需重新授权，不会自动提交生成。</p></header><p v-if="error" class="agent-message error" role="alert">{{ error }}</p><section v-if="ready" class="agent-card"><h2>免费检查已完成</h2><p>模型列表、余额查询和 OAuth 授权均已连接。</p><p v-if="balance" class="agent-message">余额 {{ balance.credits }} 丝 · 单次上限 {{ balance.max_per_job }} 丝</p><form v-if="!result" class="agent-permissions" @submit.prevent="generate"><label class="agent-field" style="display:grid">模型<select v-model="model" :disabled="busy || !!pending"><option v-for="item in models" :key="item.id" :value="item.id">{{ item.label }} · {{ item.credit_cost }} 丝 / 张</option></select></label><label class="agent-field" style="display:grid">描述<textarea v-model="prompt" rows="4" :disabled="busy || !!pending" required /></label><p class="agent-fine">点击后将提交一张图片并按当前模型价格预扣积分。修改、重试与查询均受本连接授权限制。</p><button class="agent-button primary" :disabled="busy || !model || !prompt.trim()">{{ busy ? '正在提交…' : pending ? '确认原请求（复用请求 ID）' : '提交一张测试图片' }}</button></form><div v-if="result" class="agent-test-result"><p>任务 {{ result.job_id }} · {{ result.status }} · {{ result.billing_status }}</p><img v-if="result.image_url" :src="result.image_url" alt="MCP 生成结果" /><p v-if="result.error_message">{{ result.error_message }}</p><button v-if="error" class="agent-button" @click="poll">重新查询任务</button></div></section><div class="agent-actions" style="margin-top:24px"><router-link to="/mcp" class="agent-button">返回连接管理</router-link><router-link to="/history" class="agent-button">查看生图历史</router-link></div></main></template>
