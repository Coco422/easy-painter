<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ShieldCheck } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { authState, isLoggedIn, login } from '@/lib/auth'
import { agentApi, type AgentConfig } from '@/lib/agent'
import './agent.css'

const route = useRoute()
type AuthorizationDetails = { client_name: string; redirect_uri: string; scopes: string[]; expires_at: string }
const details = ref<AuthorizationDetails>()
const config = ref<AgentConfig>(), scopes = ref<string[]>([]), single = ref(10), days = ref(30)
const identifier = ref(''), password = ref(''), error = ref(''), busy = ref(false)
const requestId = computed(() => typeof route.query.request === 'string' ? route.query.request : '')
let epoch = 0
async function load() {
  const current = ++epoch
  details.value = undefined; error.value = ''
  if (!isLoggedIn()) return
  try {
    const [next, settings] = await Promise.all([agentApi<AuthorizationDetails>(`/authorizations/${encodeURIComponent(requestId.value)}`), agentApi<AgentConfig>('/config')])
    if (current !== epoch) return
    details.value = next; config.value = settings; scopes.value = [...next.scopes]
  } catch (e) { if (current === epoch) error.value = (e as Error).message }
}
async function signIn() {
  busy.value = true; error.value = ''
  try { await login(identifier.value, password.value); password.value = ''; await load() }
  catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
async function decide(allow: boolean) {
  if (busy.value) return
  const current = epoch
  busy.value = true; error.value = ''
  try {
    const result = await agentApi<{ redirect_to: string }>(`/authorizations/${encodeURIComponent(requestId.value)}`, { method:'POST', body:JSON.stringify({ allow, scopes:scopes.value, max_per_job:single.value, days:days.value }) })
    if (current === epoch) location.assign(result.redirect_to)
  } catch (e) { if (current === epoch) error.value = (e as Error).message }
  finally { if (current === epoch) busy.value = false }
}
watch(() => authState.sessionId, () => { busy.value = false; void load() })
onMounted(load)
onBeforeUnmount(() => { epoch++ })
</script>
<template>
  <main class="agent-page agent-consent"><header class="agent-heading"><p class="agent-eyebrow">AUTHORIZE CONNECTION</p><h1>允许这个 Agent 连接吗？</h1><p>登录只确认身份。你可以在这里决定它能做什么，以及单次最多使用多少积分。</p></header>
    <p v-if="error" class="agent-message error" role="alert">{{ error }}</p>
    <section v-if="!isLoggedIn()" class="agent-card"><h2>先登录你的账号</h2><form class="agent-permissions" @submit.prevent="signIn"><label class="agent-field" style="display:grid">用户名或邮箱<input v-model="identifier" autocomplete="username" required /></label><label class="agent-field" style="display:grid">密码<input v-model="password" type="password" autocomplete="current-password" required /></label><button class="agent-button primary" :disabled="busy">登录并查看授权</button></form><router-link to="/login">注册或找回密码 →</router-link></section>
    <form v-else-if="details" class="agent-card" @submit.prevent="decide(true)"><div class="agent-section-heading"><ShieldCheck :size="24" /><div><h2>{{ details.client_name }}</h2><p>当前账号：{{ authState.user?.username ?? '已登录用户' }}</p></div></div><p class="agent-fine">客户端名称由其自行提供，请确认这是你刚才添加的连接。授权完成将返回：</p><pre>{{ details.redirect_uri }}</pre><h2>允许的能力</h2><div class="agent-permissions"><label v-for="scope in details.scopes" :key="scope"><input v-model="scopes" type="checkbox" :value="scope" :disabled="busy" />{{ config?.scopes[scope] ?? scope }}</label></div><p class="agent-fine">任务读取权限包含自己的已有任务、提示词和仍有效的原图；不提供删除、公开作品或管理后台权限。</p><div class="agent-limit-grid"><label class="agent-field">单次消费上限（丝）<input v-model.number="single" type="number" min="0" max="100000" required :disabled="busy" /></label><label class="agent-field">授权有效期<select v-model.number="days" :disabled="busy"><option :value="7">7 天</option><option :value="30">30 天</option><option :value="90">90 天</option></select></label></div><p class="agent-message">同一账号、同一份积分，不设每日消费上限。每次调用受单次上限和账号余额约束；提交时预扣，成功结算，失败退款。</p><div class="agent-actions"><button type="submit" class="agent-button primary" :disabled="busy || !scopes.length">{{ busy ? '处理中…' : '允许连接' }}</button><button type="button" class="agent-button" :disabled="busy" @click="decide(false)">拒绝</button></div><p class="agent-fine">可在「连接 Agent」页面随时调整额度或撤销授权，改密后授权失效。</p></form>
    <p v-else-if="!error" role="status" class="agent-muted">正在检查授权请求…</p>
  </main>
</template>
