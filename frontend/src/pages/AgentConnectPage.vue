<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, Check, Copy, Link2, ShieldCheck, SlidersHorizontal, Unplug } from 'lucide-vue-next'
import { authState, isLoggedIn } from '@/lib/auth'
import { agentApi, installation, startConnectionTest, type AgentConfig, type AgentConnection } from '@/lib/agent'
import './agent.css'

const client = ref('codex')
const config = ref<AgentConfig>()
const connections = ref<AgentConnection[]>([])
const error = ref(''), notice = ref(''), busy = ref(false), loading = ref(true)
const editing = ref(''), revoking = ref(''), single = ref(10)
let epoch = 0
const setup = computed(() => installation(client.value, config.value?.endpoint ?? ''))
async function load() {
  const current = ++epoch
  error.value = ''; loading.value = true
  try {
    const next = await agentApi<AgentConfig>('/config')
    if (epoch !== current) return
    config.value = next
    const rows = isLoggedIn() && next.enabled ? await agentApi<AgentConnection[]>('/connections') : []
    if (epoch === current) connections.value = rows
  } catch (e) { if (epoch === current) error.value = (e as Error).message }
  finally { if (epoch === current) loading.value = false }
}
async function copy() {
  try { await navigator.clipboard.writeText(setup.value.text); notice.value = '已复制配置。' }
  catch { error.value = '浏览器无法复制，请选中配置文本手动复制。' }
}
async function test() {
  if (!config.value?.endpoint) return
  busy.value = true; error.value = ''
  try { await startConnectionTest(config.value.endpoint) }
  catch (e) { error.value = (e as Error).message; busy.value = false }
}
async function mutate(id: string, revoke = false) {
  if (busy.value) return
  const current = epoch, session = authState.sessionId
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await agentApi(`/connections/${id}`, { method: revoke ? 'DELETE' : 'PUT', ...(revoke ? {} : { body: JSON.stringify({ max_per_job: single.value }) }) })
    if (epoch !== current) return
    editing.value = ''; revoking.value = ''
    notice.value = revoke ? '连接已断开，访问、续期和图片链接均已失效。已有任务仍继续，计费按原规则结算。' : '额度已更新，对后续提交立即生效。'
    await load()
  } catch (e) { if (epoch === current) error.value = (e as Error).message }
  finally { if (session === authState.sessionId) busy.value = false }
}
watch(() => authState.sessionId, () => { connections.value = []; editing.value = ''; revoking.value = ''; notice.value = ''; busy.value = false; void load() })
onMounted(load)
onBeforeUnmount(() => { epoch++ })
</script>

<template>
  <main class="agent-page">
    <header class="agent-heading"><div><p class="agent-eyebrow">EASY PAINTER / AGENT CONNECT</p><h1>让你的 Agent，也会画图。</h1><p>在熟悉的对话里生成、修改图片，沿用本站账号与积分。</p></div><span class="agent-badge"><ShieldCheck :size="15" />独立授权 · 消费可控</span></header>
    <p v-if="error" role="alert" class="agent-message error">{{ error }}</p>
    <p v-if="notice" role="status" class="agent-message">{{ notice }}</p>
    <p v-if="loading" role="status" class="agent-muted">正在读取连接状态…</p>
    <div class="agent-layout">
      <section class="agent-card agent-install"><div class="agent-section-heading"><span class="agent-step">01</span><div><h2>连接你的 AI 助手</h2><p>选择客户端，添加服务后在浏览器确认授权。</p></div></div>
        <div class="agent-tabs" role="group" aria-label="选择 AI 助手"><button v-for="item in [{ id:'codex', name:'Codex' },{ id:'cursor', name:'Cursor' },{ id:'claude', name:'Claude' },{ id:'dsh', name:'dsh' },{ id:'other', name:'其他客户端' }]" :key="item.id" :aria-pressed="client === item.id" @click="client = item.id">{{ item.name }}</button></div>
        <template v-if="config?.enabled"><p class="agent-setup-hint">{{ setup.hint }}</p><pre tabindex="0"><code>{{ setup.text }}</code></pre><div class="agent-actions"><a v-if="setup.link" :href="setup.link" class="agent-button primary"><Link2 :size="16" />安装到 Cursor<ArrowUpRight :size="15" /></a><button class="agent-button" @click="copy"><Copy :size="15" />复制{{ client === 'codex' || client === 'claude' ? '安装命令' : '配置' }}</button><button class="agent-button" :disabled="busy" @click="test">{{ busy ? '正在连接…' : '在网页测试连接' }}</button></div><p class="agent-fine">配置中不含密码或令牌。安装不代表授权，只有你确认后 Agent 才能使用积分。</p><p v-if="config.endpoint?.startsWith('http:')" class="agent-message">当前是本机预览地址，仅供本地客户端测试；云端助手需使用部署后的 HTTPS 地址。</p></template>
        <p v-else-if="!loading" class="agent-message">管理员尚未启用 Agent 接入。配置正式服务地址并完成数据库迁移后即可连接。</p>
      </section>
      <aside class="agent-card agent-summary"><span class="agent-step">02</span><h2>授权给谁，用多少，由你决定。</h2><ul><li><Check :size="16" /><div><strong>单独授权</strong><p>只开放你勾选的能力，网页登录凭证不交给 Agent。</p></div></li><li><Check :size="16" /><div><strong>单次消费保护</strong><p>单次上限由你设定，日消费不设上限；按账号余额使用。</p></div></li><li><Check :size="16" /><div><strong>随时断开</strong><p>撤销连接后，后续调用与续期立即失效。</p></div></li></ul><a href="/mcp/install.md" target="_blank" rel="noopener" class="agent-doc-link">AI 安装说明<ArrowUpRight :size="14" /></a></aside>
    </div>
    <section class="agent-card agent-connections"><div class="agent-section-heading"><SlidersHorizontal :size="20" /><div><h2>已授权的连接</h2><p>可调整单次消费上限；修改上限不取消已提交任务。</p></div><button v-if="isLoggedIn()" class="agent-button" :disabled="busy || loading" @click="load">刷新</button></div>
      <p v-if="!isLoggedIn()" class="agent-muted">登录后管理你的连接。<router-link to="/login?redirect=/mcp">登录账号 →</router-link></p>
      <p v-else-if="!connections.length && !loading" class="agent-muted">还没有连接。从上方添加服务，或先在网页体验一次授权流程。</p>
      <article v-for="item in connections" :key="item.id" class="agent-connection"><div class="agent-connection-title"><strong>{{ item.label }}</strong><span :class="['agent-status',{ inactive: !item.active }]">{{ item.active ? '已连接' : '已失效' }}</span><time>到期 {{ new Date(item.expires_at).toLocaleDateString('zh-CN') }}</time></div><p class="agent-muted">{{ item.scopes.map(scope => config?.scopes[scope] ?? scope).join(' · ') }}</p><div class="agent-connection-bottom"><span>单次 <strong>{{ item.max_per_job }}</strong> 丝</span><div class="agent-actions"><button v-if="item.active" class="agent-button" :disabled="busy" @click="editing = item.id; single = item.max_per_job; revoking = ''">调整额度</button><button v-if="item.active" class="agent-button" :disabled="busy" @click="revoking = item.id; editing = ''"><Unplug :size="14" />断开</button></div></div>
        <form v-if="editing === item.id" class="agent-inline-form" @submit.prevent="mutate(item.id)"><label>单次上限（丝）<input v-model.number="single" type="number" min="0" max="100000" required /></label><button class="agent-button primary" :disabled="busy">保存额度</button><button type="button" class="agent-button" @click="editing = ''">取消</button></form>
        <div v-if="revoking === item.id" class="agent-inline-form"><p>断开后需重新授权。已提交任务仍继续执行。</p><button class="agent-button primary" :disabled="busy" @click="mutate(item.id,true)">确认断开</button><button class="agent-button" @click="revoking = ''">取消</button></div>
      </article>
    </section>
    <section class="agent-resources"><div><p class="agent-eyebrow">SKILL + MCP</p><h2>接上工具，再教会它怎么用。</h2><p>Skill 帮助助手选择模型、估算消耗、组织描述和继续改图。首版提供 6 个工具，每次生成一张，失败按本站规则退款。</p></div><div class="agent-resource-links"><a href="/mcp/easy-painter-skill.zip" class="agent-button">下载 Easy Painter Skill<ArrowUpRight :size="15" /></a><a href="/llms-full.txt" target="_blank" rel="noopener" class="agent-button">AI 可读能力说明<ArrowUpRight :size="15" /></a></div></section>
  </main>
</template>
