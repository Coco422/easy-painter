import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, createJob, fetchJob, uploadReferenceImage } from '@/lib/api'
import { authState, fetchImageFile, fetchCurrentUser } from '@/lib/auth'
import { randomId } from '@/lib/browser-crypto'
import { buildCreationPrompt } from '@/lib/creation-presets'
import { creationHistoryKey, creationVersionRows, emptyCreationHistory, MAX_CREATION_VERSIONS, parseCreationHistory } from '@/lib/creation-versions'
import { mediaAvailable, sameOriginMedia } from '@/lib/media-state'
import { defaultGenerationSize } from '@/lib/generation-sizes'
import { assetIds, MAX_ASSETS, MAX_PROJECT_BYTES, newProject } from '@/lib/canvas/model'
import { appendGenerationImage } from '@/lib/canvas/from-generation'
import { getAsset, getProject, listProjects, makeAsset, saveProject } from '@/lib/canvas/storage'
import type { CreateJobRequest, CreateJobResponse, ImageSize, JobDetailResponse, PublicModel } from '@/lib/types'

export function useCreationVersions(options: {
  jobs: Ref<JobDetailResponse[]>
  membership: Ref<Record<string, string>>
  models: Ref<PublicModel[]>
  selectedModel: Ref<string>
  selectedSize: Ref<ImageSize>
  maxLength: Ref<number>
  feedback: Ref<string>
  register: (result: CreateJobResponse, request: CreateJobRequest) => void
  restore: (job: JobDetailResponse) => void
}) {
  const router = useRouter()
  const history = ref(emptyCreationHistory())
  const selectedId = ref('')
  const busy = ref(false)
  const storageError = ref('')
  const canvases = ref<{ id: string; title: string }[]>([])
  const selectedJob = computed(() => options.jobs.value.find(job => job.job_id === selectedId.value))
  const editModel = computed(() => {
    const supported = options.models.value.filter(model => model.enabled && model.supports_reference_image && model.max_reference_images > 0)
    return supported.find(model => model.id === options.selectedModel.value) ?? supported.find(model => model.id === selectedJob.value?.model) ?? supported[0]
  })
  const editSize = computed(() => {
    const sizes = editModel.value?.supported_sizes ?? []
    if (!sizes.length || sizes.includes(options.selectedSize.value)) return options.selectedSize.value
    if (selectedJob.value && sizes.includes(selectedJob.value.size)) return selectedJob.value.size as ImageSize
    return defaultGenerationSize(sizes)
  })
  let epoch = 0
  let disposed = false
  const controllers = new Set<AbortController>()
  function scope() {
    const owner = authState.user?.id, session = authState.sessionId, operation = epoch
    if (!owner || !session) throw new Error('请先登录后再继续创作。')
    return () => {
      if (disposed || operation !== epoch || owner !== authState.user?.id || session !== authState.sessionId) throw new Error('登录状态已变化，请重新打开创作台。')
      return owner
    }
  }
  function persist() {
    const owner = authState.user?.id
    if (!owner) throw new Error('登录状态已变化。')
    history.value.parents = Object.fromEntries(Object.entries(history.value.parents).slice(-MAX_CREATION_VERSIONS))
    try { localStorage.setItem(creationHistoryKey(owner), JSON.stringify(history.value)); storageError.value = '' }
    catch { storageError.value = '浏览器无法保存版本记录，请检查存储空间；生图历史仍保存在服务器。'; throw new Error(storageError.value) }
  }
  function record(id: string, parent: string | null = null) {
    if (Object.prototype.hasOwnProperty.call(history.value.parents, id)) {
      return
    }
    history.value.parents[id] = parent
    try { persist() } catch (error) { options.feedback.value = (error as Error).message }
  }
  function forget(id: string) {
    delete history.value.parents[id]
    if (selectedId.value === id) selectedId.value = options.jobs.value.find(job => job.job_id !== id)?.job_id ?? ''
    try { persist() } catch (error) { options.feedback.value = (error as Error).message }
  }
  async function load() {
    if (!authState.user?.id) return
    const assertOwner = scope(), owner = assertOwner()
    try { history.value = parseCreationHistory(localStorage.getItem(creationHistoryKey(owner))) }
    catch { history.value = emptyCreationHistory(); storageError.value = '浏览器无法读取本地版本记录，请检查浏览器存储设置。' }
    const ids = Object.keys(history.value.parents).filter(id => !options.jobs.value.some(job => job.job_id === id))
    // A bounded restore avoids flooding the server with one request per historical job.
    for (let index = 0; index < ids.length; index += 5) {
      assertOwner()
      await Promise.all(ids.slice(index, index + 5).map(async id => {
        try { const job = await fetchJob(id); assertOwner(); options.restore(job) }
        catch (error) {
          assertOwner()
          if (error instanceof ApiError && [403, 404, 410].includes(error.status)) delete history.value.parents[id]
          else options.feedback.value = '部分版本暂时无法恢复，请刷新重试。'
        }
      }))
    }
    assertOwner()
    selectedId.value = ''
    try {
      const projects = await listProjects(owner)
      assertOwner()
      canvases.value = projects
    } catch (error) { assertOwner(); options.feedback.value = `本地画布暂不可用：${(error as Error).message}` }
  }
  async function sourceBlob(job: JobDetailResponse, assertOwner: () => string) {
    const available = () => job.status === 'succeeded' && job.image_url && mediaAvailable(job.media_state ?? 'none', job.media_expires_at)
    if (!available() || !sameOriginMedia(job.image_url!, location.origin)) throw new Error('原图已过期或不可访问，请选择其他版本。')
    const controller = new AbortController()
    controllers.add(controller)
    try {
      const response = await fetchImageFile(job.image_url!, { signal: controller.signal })
      assertOwner()
      if (!response.ok) throw new Error('无法取得原图，请刷新图片或选择其他版本。')
      const blob = await response.blob()
      assertOwner()
      if (!available()) throw new Error('原图已过期，请选择其他版本。')
      return blob
    } finally { controllers.delete(controller) }
  }
  async function transmit(assertOwner: () => string) {
    const pending = history.value.pending
    if (!pending) return
    try {
      const result = await createJob(pending.request, pending.key)
      assertOwner()
      history.value.parents[result.job_id] = pending.parentId
      history.value.pending = null
      options.register(result, pending.request)
      selectedId.value = result.job_id
      options.feedback.value = '修改任务已提交，原版本会保留。'
      try { persist() } catch (error) { options.feedback.value += ` ${(error as Error).message}` }
      void fetchCurrentUser()
    } catch (error) {
      assertOwner()
      if (error instanceof ApiError && error.status < 500 && ![408].includes(error.status)) {
        history.value.pending = null
        persist()
        throw error
      }
      options.feedback.value = '提交结果尚未确认。请点击“确认上次改图任务”，将使用原请求 ID 确认，避免重复扣费。'
    }
  }
  async function action(fn: (assertOwner: () => string) => Promise<void>) {
    if (busy.value) return
    const operation = epoch
    busy.value = true
    options.feedback.value = ''
    try { await fn(scope()) }
    catch (error) { if (operation === epoch && !disposed) options.feedback.value = (error as Error).message }
    finally { if (operation === epoch && !disposed) busy.value = false }
  }
  async function revise(instruction: string) {
    await action(async assertOwner => {
      if (history.value.pending) throw new Error('请先确认上次改图任务。')
      const source = selectedJob.value, model = editModel.value, size = editSize.value
      const prompt = buildCreationPrompt(instruction, { mode: 'edit', template: 'free', style: 'auto', language: 'auto' })
      if (!prompt || prompt.length > options.maxLength.value) throw new Error(`请填写修改要求，含补充说明不超过 ${options.maxLength.value} 字。`)
      if (!source || !model) throw new Error('请选择已完成的版本，以及支持参考图的模型。')
      await submitFromSource(source, prompt, model.id, size, assertOwner)
    })
  }
  async function submitFromSource(source: JobDetailResponse, prompt: string, model: string, size: ImageSize, assertOwner: () => string) {
    const blob = await sourceBlob(source, assertOwner)
    const uploaded = await uploadReferenceImage(new File([blob], `version-${source.job_id}.${blob.type === 'image/jpeg' ? 'jpg' : blob.type === 'image/webp' ? 'webp' : 'png'}`, { type: blob.type }))
    assertOwner()
    history.value.pending = { key: randomId(), parentId: source.job_id, request: { prompt, model, size, reference_image_ids: [uploaded.id] } }
    // Persist the exact paid request before posting. Confirmation never re-uploads or changes it.
    persist()
    await transmit(assertOwner)
  }
  async function retryRevision(job: JobDetailResponse) {
    await action(async assertOwner => {
      if (history.value.pending) throw new Error('请先确认上次改图任务。')
      const source = options.jobs.value.find(item => item.job_id === history.value.parents[job.job_id])
      const model = options.models.value.find(item => item.id === job.model && item.enabled && item.supports_reference_image)
      if (!source || !model || (model.supported_sizes.length && !model.supported_sizes.includes(job.size))) throw new Error('原版本或原模型参数不可用，请选择一个已完成的版本重新修改。')
      if (job.prompt.length > options.maxLength.value) throw new Error('原提示词超过当前长度限制，请从原版本重新修改。')
      // A failed edit retries against its original parent, never unrelated sidebar references.
      await submitFromSource(source, job.prompt, model.id, job.size as ImageSize, assertOwner)
    })
  }
  const confirm = () => action(async assertOwner => { persist(); await transmit(assertOwner) })
  async function addToCanvas(job: JobDetailResponse, targetId: string) {
    await action(async assertOwner => {
      const owner = assertOwner(), blob = await sourceBlob(job, assertOwner)
      const item = await makeAsset(owner, blob, `创作-${job.job_id}.png`)
      assertOwner()
      const row = creationVersionRows(options.jobs.value, history.value.parents, options.membership.value).find(row => row.job.job_id === job.job_id)
      const label = row ? `第 ${row.batchNumber} ${row.candidateCount > 1 ? '批' : '次绘图'} · ${row.label}` : '创作图片'
      const project = targetId ? await getProject(owner, targetId) : newProject(owner, label)
      assertOwner()
      if (!project) throw new Error('目标画布已移除，请重新选择。')
      const bitmap = await createImageBitmap(blob)
      const width = bitmap.width, height = bitmap.height
      bitmap.close()
      const next = appendGenerationImage(project, { jobId: job.job_id, assetId: item.id, label, prompt: job.prompt, model: job.model, size: job.size, width, height })
      const ids = assetIds(next)
      if (ids.length > MAX_ASSETS) throw new Error('目标画布素材已达上限，请新建画布。')
      let bytes = item.blob.size
      for (const id of ids.filter(id => id !== item.id)) bytes += (await getAsset(owner, id)).blob.size
      assertOwner()
      if (bytes > MAX_PROJECT_BYTES) throw new Error('目标画布素材超过 128 MB，请新建画布。')
      next.revision = await saveProject(next, [item])
      assertOwner()
      await router.push(`/canvas/${next.id}`)
    })
  }
  watch(() => authState.sessionId, () => {
    epoch++
    controllers.forEach(controller => controller.abort())
    history.value = emptyCreationHistory()
    selectedId.value = ''
    canvases.value = []
    busy.value = false
    storageError.value = ''
  })
  onBeforeUnmount(() => { disposed = true; epoch++; controllers.forEach(controller => controller.abort()) })
  return { history, selectedId, busy, storageError, canvases, editModel, editSize, load, record, forget, revise, retryRevision, confirm, addToCanvas }
}
