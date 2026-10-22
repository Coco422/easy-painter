// Development-only fixtures for the creation workspace. Never imported by the app bundle.
import type { ImageSize, JobStatus, PublicModel, UserInfo } from '../src/lib/types'

export interface MockJobSeed {
  id: string
  prompt: string
  model?: string
  size?: ImageSize
  batch?: string
  parent?: string | null
  status?: JobStatus
  /** Seconds after the scenario's t0 when the job settles. */
  settleAfter?: number
  failAfter?: number
  errorMessage?: string
  mediaState?: 'available' | 'expired' | 'none'
  expiresInHours?: number | null
  brokenMedia?: boolean
  creditCost?: number
}

export interface MockScenario {
  label: string
  detail: string
  credits: number
  models?: PublicModel[]
  jobs: MockJobSeed[]
  submit?: 'ok' | 'insufficient' | 'slow' | 'unknown'
  /** Deterministic ageing so a scenario looks the same on every reload. */
  ageMinutes?: number
}

export const mockModels: PublicModel[] = [
  {
    id: 'gpt-image-2', label: 'GPT-Image-2', enabled: true,
    supports_reference_image: true, max_reference_images: 5,
    supported_sizes: ['auto', '1024x1024', '1280x720', '720x1280', '1536x1024', '1024x1536'],
    base_credit_cost: 8, credit_cost: 5,
    credit_cost_by_size: { auto: 5, '1k': 5, '2k': 9, '4k': 15 },
    base_credit_cost_by_size: { auto: 8, '1k': 8, '2k': 12, '4k': 20 },
  },
  {
    id: 'seedream-4', label: 'Seedream 4', enabled: true,
    supports_reference_image: true, max_reference_images: 5,
    supported_sizes: ['auto', '1024x1024', '2048x1152', '1152x2048'],
    base_credit_cost: 6, credit_cost: 4,
    credit_cost_by_size: { auto: 4, '1k': 4, '2k': 7, '4k': 12 },
    base_credit_cost_by_size: { auto: 6, '1k': 6, '2k': 10, '4k': 16 },
  },
  {
    id: 'flux-kontext', label: 'Flux Kontext', enabled: true,
    supports_reference_image: false, max_reference_images: 0,
    supported_sizes: ['auto', '1024x1024', '1792x1024'],
    base_credit_cost: 5, credit_cost: 5,
    credit_cost_by_size: { auto: 5, '1k': 5, '2k': 5, '4k': 5 },
    base_credit_cost_by_size: { auto: 5, '1k': 5, '2k': 5, '4k': 5 },
  },
]

const lighthouse = '悬崖边的灯塔，黄昏，湿润的空气，远处有雨，暖色前景与冷色天空对照'
const botanical = '一页植物标本图鉴，银杏与蕨类并列，米色纸张，手写标注，克制的墨线'
const poster = '读书分享会海报，标题“在文字里相遇”，周六 14:00，温暖的阅读氛围'
const product = '一只白色陶瓷杯放在木质书桌上，旁边有翻开的书，柔和晨间自然光'

export const mockScenarios: Record<string, MockScenario> = {
  idle: {
    label: '空闲 · 有历史',
    detail: '余额 245 丝，已完成 3 次绘图，右栏为空闲引导',
    credits: 245,
    jobs: [
      { id: 'job-a1', prompt: lighthouse, settleAfter: -9999, size: '1280x720', batch: 'b1' },
      { id: 'job-a2', prompt: botanical, settleAfter: -9999, size: '1024x1024', batch: 'b2' },
      { id: 'job-a3', prompt: poster, settleAfter: -9999, size: '1024x1536', batch: 'b3' },
    ],
  },
  empty: {
    label: '空闲 · 全新账号',
    detail: '没有任何作品，只显示一句引导',
    credits: 245,
    jobs: [],
  },
  'generating-single': {
    label: '单张生成中',
    detail: '一个任务正在绘制，12 秒后自动完成，可看到状态切换',
    credits: 240,
    jobs: [
      { id: 'job-a1', prompt: botanical, settleAfter: -9999, size: '1024x1024', batch: 'b0' },
      { id: 'job-g1', prompt: lighthouse, settleAfter: 12, size: '1280x720', batch: 'b1' },
    ],
  },
  'generating-batch': {
    label: '4 张候选 · 混合状态',
    detail: '2 张完成、1 张绘制中、1 张失败已退款；15 秒后全部结束',
    credits: 230,
    jobs: [
      { id: 'job-b1', prompt: lighthouse, settleAfter: -9999, size: '1280x720', batch: 'b1' },
      { id: 'job-b2', prompt: lighthouse, settleAfter: -9999, size: '1280x720', batch: 'b1' },
      { id: 'job-b3', prompt: lighthouse, settleAfter: 15, size: '1280x720', batch: 'b1' },
      { id: 'job-b4', prompt: lighthouse, failAfter: 8, errorMessage: '上游返回的内容审核未通过', size: '1280x720', batch: 'b1' },
    ],
  },
  'batch-all-live': {
    label: '4 张全部进行中',
    detail: '候选栏 4 个缩略图同时转圈，30 秒后依次完成',
    credits: 220,
    jobs: [
      { id: 'job-c1', prompt: product, settleAfter: 18, size: '1024x1024', batch: 'b1' },
      { id: 'job-c2', prompt: product, settleAfter: 24, size: '1024x1024', batch: 'b1' },
      { id: 'job-c3', prompt: product, settleAfter: 30, size: '1024x1024', batch: 'b1' },
      { id: 'job-c4', prompt: product, settleAfter: 36, size: '1024x1024', batch: 'b1' },
    ],
  },
  'queued-long': {
    label: '长排队',
    detail: '任务停在排队中，用来检查“排队”和“绘制中”是否可区分',
    credits: 240,
    jobs: [
      { id: 'job-q1', prompt: poster, settleAfter: 120, size: '1024x1536', batch: 'b1' },
    ],
  },
  'edit-branch': {
    label: '修改分支 V1 → V2 → V3',
    detail: '一张图的两代修改，选中 V3，可切换回原图分叉',
    credits: 226,
    jobs: [
      { id: 'job-e1', prompt: lighthouse, settleAfter: -9999, size: '1280x720', batch: 'b1' },
      { id: 'job-e2', parent: 'job-e1', prompt: lighthouse + '\n\n改成清晨的光线，保留灯塔结构', settleAfter: -9999, size: '1280x720', batch: 'b1' },
      { id: 'job-e3', parent: 'job-e2', prompt: lighthouse + '\n\n把海面换成平静的雾', settleAfter: -9999, size: '1280x720', batch: 'b1' },
    ],
  },
  failed: {
    label: '失败并退款',
    detail: '单张失败，计费显示已全额退回',
    credits: 245,
    jobs: [
      { id: 'job-f1', prompt: botanical, failAfter: -9999, errorMessage: '上游通道超时，已自动重试 3 次', size: '1024x1024', batch: 'b1' },
    ],
  },
  expired: {
    label: '图片已过期',
    detail: '媒体过期后的占位与提示',
    credits: 245,
    jobs: [
      { id: 'job-x1', prompt: botanical, settleAfter: -9999, mediaState: 'expired', expiresInHours: -3, size: '1024x1024', batch: 'b1' },
    ],
  },
  'broken-media': {
    label: '图片加载失败',
    detail: '媒体接口返回 404，检查重试与占位文案',
    credits: 245,
    jobs: [
      { id: 'job-r1', prompt: product, settleAfter: -9999, brokenMedia: true, size: '1024x1024', batch: 'b1' },
    ],
  },
  'few-credits': {
    label: '余额不足',
    detail: '提交时返回 402，检查提示与跳转',
    credits: 3,
    submit: 'insufficient',
    jobs: [],
  },
  'submit-slow': {
    label: '提交缓慢',
    detail: '提交延迟 2.5 秒，检查按钮的进行中状态',
    credits: 245,
    submit: 'slow',
    jobs: [],
  },
  'submit-unknown': {
    label: '提交结果未知',
    detail: '服务端 503，检查“结果尚未确认”的保护路径',
    credits: 245,
    submit: 'unknown',
    jobs: [],
  },
}

export const mockUser: UserInfo = {
  id: 'mock-owner',
  username: 'mock_painter',
  email: 'mock@example.com',
  display_name: '演示画师',
  is_public: true,
  credits: 245,
  created_at: '2026-01-01T00:00:00Z',
}
