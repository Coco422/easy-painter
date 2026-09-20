import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'
import {
  ApiError,
  createJob,
  fetchJob,
  fetchPublicMeta,
  uploadReferenceImage,
} from '@/lib/api'
import { authState, fetchCurrentUser, getAuthHeader } from '@/lib/auth'
import { mediaAvailable, sameOriginMedia } from '@/lib/media-state'
import type { ImageSize, PublicMetaResponse } from '@/lib/types'
import {
  assetIds,
  clone,
  generationInputs,
  MAX_ASSETS,
  MAX_NODES,
  MAX_PROJECT_BYTES,
  newNode,
  uid,
} from './model'
import type { CanvasAsset, CanvasProject, CanvasRun, Point } from './model'
import { getAsset, makeAsset, saveProject } from './storage'
import { syncProject } from './cloud'

export function useCanvasSession(initial: CanvasProject) {
  const project = ref(clone(initial)),
    meta = shallowRef<PublicMetaResponse | null>(null)
  const selected = ref<string[]>([]),
    urls = ref<Record<string, string>>({})
  const feedback = ref(''),
    saveState = ref('已保存到此浏览器'),
    cloudState = ref(''),
    busy = ref(false)
  const pendingAssets = new Map<string, CanvasAsset>(),
    past: { nodes: CanvasProject['nodes']; edges: CanvasProject['edges'] }[] =
      [],
    future: typeof past = []
  const historyVersion = ref(0),
    canUndo = computed(() => (historyVersion.value, past.length > 0)),
    canRedo = computed(() => (historyVersion.value, future.length > 0))
  const ownerId = initial.ownerId,
    token = authState.token
  let disposed = false,
    editVersion = 0,
    saveTimer: ReturnType<typeof setTimeout> | undefined,
    pollTimer: ReturnType<typeof setTimeout> | undefined
  let saving: Promise<void> | null = null,
    syncing = false,
    pollBusy = false
  let cloudTimer: ReturnType<typeof setTimeout> | undefined
  let syncIntent = 0
  function assertOwner() {
    if (disposed || authState.user?.id !== ownerId || authState.token !== token)
      throw new Error('登录状态已变化，请重新打开画布。')
  }
  function checkpoint() {
    past.push(clone({ nodes: project.value.nodes, edges: project.value.edges }))
    if (past.length > 50) past.shift()
    future.length = 0
    historyVersion.value++
  }
  function changed(syncCloud = true) {
    editVersion++
    project.value.updatedAt = new Date().toISOString()
    saveState.value = '尚未保存'
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      void flush().catch((e) => {
        feedback.value = e.message
      })
    }, 450)
    if (syncCloud && project.value.cloudEnabled) {
      cloudState.value = '云端待同步'
      clearTimeout(cloudTimer)
      cloudTimer = setTimeout(() => {
        void sync()
      }, 5000)
    }
  }
  async function flush(): Promise<void> {
    assertOwner()
    clearTimeout(saveTimer)
    if (saving) {
      await saving
      if (saveState.value !== '已保存到此浏览器') return flush()
      return
    }
    if (saveState.value === '已保存到此浏览器' && !pendingAssets.size) return
    const version = editVersion,
      snapshot = clone(project.value),
      assets = [...pendingAssets.values()]
    saveState.value = '正在保存…'
    saving = (async () => {
      try {
        const revision = await saveProject(snapshot, assets)
        project.value.revision = revision
        for (const asset of assets) pendingAssets.delete(asset.id)
        saveState.value =
          version === editVersion ? '已保存到此浏览器' : '尚未保存'
      } catch (e) {
        saveState.value = '保存失败'
        throw e
      } finally {
        saving = null
      }
    })()
    await saving
    if (version !== editVersion) return flush()
  }
  function historyMove(direction: 'undo' | 'redo') {
    const from = direction === 'undo' ? past : future,
      to = direction === 'undo' ? future : past,
      snapshot = from.pop()
    if (!snapshot) return
    to.push(clone({ nodes: project.value.nodes, edges: project.value.edges }))
    project.value.nodes = snapshot.nodes
    project.value.edges = snapshot.edges
    for (const run of project.value.runs) {
      const node = project.value.nodes.find((n) => n.id === run.nodeId)
      if (node && run.assetId) node.assetId = run.assetId
    }
    selected.value = []
    historyVersion.value++
    changed()
    void loadImages()
  }
  async function asset(id: string) {
    return pendingAssets.get(id) ?? getAsset(ownerId, id)
  }
  async function reserveAsset(item: CanvasAsset) {
    const ids = assetIds(project.value)
    if (!ids.includes(item.id) && ids.length >= MAX_ASSETS)
      throw new Error('单张画布最多保存 1000 份素材，请另建画布。')
    let bytes = ids.includes(item.id) ? 0 : item.blob.size
    for (const id of ids) bytes += (await asset(id)).blob.size
    if (bytes > MAX_PROJECT_BYTES)
      throw new Error(
        '本张画布素材超过 128 MB，请另建画布。生成结果仍可从生图历史下载。',
      )
    assertOwner()
    pendingAssets.set(item.id, item)
  }
  async function loadImages() {
    for (const id of assetIds(project.value)) {
      if (urls.value[id]) continue
      try {
        const item = await asset(id)
        assertOwner()
        urls.value[id] = URL.createObjectURL(item.blob)
      } catch (e) {
        if (!disposed) feedback.value = (e as Error).message
      }
    }
  }
  async function addImage(blob: Blob, name: string, point: Point) {
    assertOwner()
    if (project.value.nodes.length >= MAX_NODES)
      throw new Error('单张画布最多 300 个节点。')
    const item = await makeAsset(ownerId, blob, name)
    assertOwner()
    const bitmap = await createImageBitmap(blob)
    const node = newNode('image', point)
    node.assetId = item.id
    node.title = name.slice(0, 120)
    node.height = Math.max(
      100,
      Math.min(700, (node.width * bitmap.height) / bitmap.width + 40),
    )
    bitmap.close()
    await reserveAsset(item)
    checkpoint()
    project.value.nodes.push(node)
    selected.value = [node.id]
    changed()
    await flush()
    await loadImages()
  }
  async function submitRun(run: CanvasRun) {
    assertOwner()
    // The key and exact payload were persisted before any POST. Network retries reuse them.
    run.status = 'submitting'
    run.error = undefined
    changed()
    await flush()
    assertOwner()
    try {
      const response = await createJob(
        {
          prompt: run.prompt,
          model: run.model,
          size: run.size as ImageSize,
          reference_image_ids: run.uploadedIds,
        },
        run.id,
      )
      assertOwner()
      run.jobId = response.job_id
      run.status = response.status === 'processing' ? 'processing' : 'queued'
      changed()
      await flush()
      void fetchCurrentUser()
      schedulePoll()
    } catch (error) {
      if (disposed) return
      run.status =
        error instanceof ApiError && error.status < 500 && error.status !== 408
          ? 'failed'
          : 'unknown'
      run.error = error instanceof Error ? error.message : '提交失败'
      if (run.status === 'unknown')
        run.error =
          '尚未确认提交结果。点击“确认任务”将使用原请求 ID 查询式重试，不重复创建任务。'
      changed()
      await flush()
    }
  }
  async function generate(nodeId: string) {
    if (busy.value) return
    busy.value = true
    feedback.value = ''
    try {
      assertOwner()
      const node = project.value.nodes.find((n) => n.id === nodeId)
      if (!node || node.type !== 'generation') return
      const config = meta.value?.models.find(
          (m) => m.id === node.model && m.enabled,
        ),
        inputs = generationInputs(project.value, nodeId)
      const prompt = [inputs.text, node.prompt?.trim()]
        .filter(Boolean)
        .join('\n\n')
      if (!config) throw new Error('请选择可用的模型。')
      if (!prompt || prompt.length > (meta.value?.prompt_max_length ?? 4000))
        throw new Error(
          `请填写提示词，总长度不超过 ${meta.value?.prompt_max_length ?? 4000} 字。`,
        )
      if (inputs.assets.length && !config.supports_reference_image)
        throw new Error('此模型不支持参考图片。')
      if (inputs.assets.length > config.max_reference_images)
        throw new Error(
          `此模型最多支持 ${config.max_reference_images} 张参考图。`,
        )
      const count = [1, 2, 4].includes(node.count ?? 1) ? (node.count ?? 1) : 1
      if (
        project.value.nodes.length + count > MAX_NODES ||
        project.value.runs.length + count > 1000
      )
        throw new Error('此画布已达到容量上限，请新建画布。')
      const uploadedIds: string[] = []
      // Never silently evict the user's reference library to make room.
      for (const id of inputs.assets) {
        const a = await asset(id)
        assertOwner()
        const uploaded = await uploadReferenceImage(
          new File([a.blob], a.name, { type: a.blob.type }),
        )
        assertOwner()
        uploadedIds.push(uploaded.id)
      }
      checkpoint()
      const runs: CanvasRun[] = []
      for (let i = 0; i < count; i++) {
        const output = newNode('image', {
          x: node.x + node.width + 90,
          y: node.y + i * 300,
        })
        output.title = `生成结果 ${i + 1}`
        project.value.nodes.push(output)
        project.value.edges.push({ id: uid(), from: node.id, to: output.id })
        const run: CanvasRun = {
          id: uid(),
          nodeId: output.id,
          sourceId: node.id,
          prompt,
          model: config.id,
          size: node.size ?? 'auto',
          referenceIds: inputs.assets,
          uploadedIds,
          status: 'preparing',
        }
        project.value.runs.push(run)
        runs.push(project.value.runs[project.value.runs.length - 1])
      }
      changed()
      await flush()
      for (const run of runs) await submitRun(run)
    } catch (e) {
      feedback.value = (e as Error).message
    } finally {
      busy.value = false
    }
  }
  async function cacheResult(
    run: CanvasRun,
    job: Awaited<ReturnType<typeof fetchJob>>,
  ) {
    if (run.assetId) return
    if (
      !job.image_url ||
      !mediaAvailable(
        job.media_state ?? 'available',
        job.media_expires_at,
        Date.now(),
      )
    ) {
      run.mediaError = '远程图片已不可用，未取得本地副本。'
      return
    }
    if (!sameOriginMedia(job.image_url, location.origin))
      throw new Error('生成结果地址不受支持。')
    const response = await fetch(job.image_url, {
      headers: getAuthHeader(),
      credentials: 'same-origin',
    })
    if (!response.ok)
      throw new Error('图片已生成，但本地保存失败。请重试获取图片。')
    const item = await makeAsset(
      ownerId,
      await response.blob(),
      `生成-${run.jobId}.png`,
    )
    assertOwner()
    await reserveAsset(item)
    run.assetId = item.id
    run.mediaError = undefined
    const node = project.value.nodes.find((n) => n.id === run.nodeId)
    if (node) node.assetId = item.id
    changed()
    await flush()
    await loadImages()
  }
  function schedulePoll() {
    clearTimeout(pollTimer)
    if (!disposed)
      pollTimer = setTimeout(
        () => {
          void poll()
        },
        Math.max(2000, meta.value?.polling_interval_ms ?? 2000),
      )
  }
  async function poll() {
    if (pollBusy || disposed) return
    pollBusy = true
    try {
      for (const run of project.value.runs.filter(
        (r) =>
          r.jobId &&
          (['queued', 'processing'].includes(r.status) ||
            (r.status === 'succeeded' && !r.assetId && !r.mediaError)),
      )) {
        assertOwner()
        try {
          const job = await fetchJob(run.jobId!)
          assertOwner()
          run.status = job.status
          run.error = job.error_message ?? undefined
          if (job.status === 'succeeded') {
            try {
              await cacheResult(run, job)
            } catch (e) {
              run.mediaError = (e as Error).message
            }
          }
          if (job.status === 'succeeded' || job.status === 'failed')
            void fetchCurrentUser()
          changed()
          await flush()
        } catch (e) {
          if (disposed) break
          if (e instanceof ApiError && [403, 404, 410].includes(e.status)) {
            run.status = 'failed'
            run.error = '任务已不可访问。'
            changed()
          } else feedback.value = (e as Error).message
        }
      }
    } finally {
      pollBusy = false
      if (
        project.value.runs.some((r) =>
          ['queued', 'processing'].includes(r.status),
        )
      )
        schedulePoll()
    }
  }
  async function retry(run: CanvasRun) {
    try {
      if (
        run.status === 'unknown' ||
        run.status === 'submitting' ||
        run.status === 'preparing'
      )
        await submitRun(run)
      else if (run.status === 'succeeded' && run.assetId) {
        await flush()
        await loadImages()
        run.mediaError = undefined
        changed()
      } else if (run.status === 'succeeded') {
        run.mediaError = undefined
        await poll()
      }
    } catch (e) {
      feedback.value = (e as Error).message
    }
  }
  async function sync() {
    if (syncing) return
    const intent = syncIntent
    syncing = true
    cloudState.value = '同步中…'
    clearTimeout(cloudTimer)
    try {
      await flush()
      const snapshot = clone(project.value),
        before = editVersion,
        version = await syncProject(snapshot, assertOwner)
      const newerEdits = before !== editVersion
      project.value.cloudVersion = version
      project.value.cloudEnabled = intent === syncIntent
      changed(false)
      await flush()
      if (!project.value.cloudEnabled) {
        cloudState.value = '自动同步已关闭'
        return
      }
      cloudState.value = newerEdits ? '云端待同步' : '已保存到云端'
      if (newerEdits)
        cloudTimer = setTimeout(() => {
          void sync()
        }, 5000)
    } catch (e) {
      if (
        disposed ||
        authState.user?.id !== ownerId ||
        authState.token !== token
      )
        return
      cloudState.value = '云端未同步'
      feedback.value = (e as Error).message
      // A conflict or lost entitlement must not trigger a repeated background write loop.
      project.value.cloudEnabled = false
      changed(false)
    } finally {
      syncing = false
    }
  }
  function stopSync() {
    syncIntent++
    project.value.cloudEnabled = false
    clearTimeout(cloudTimer)
    cloudState.value = '自动同步已关闭'
    changed(false)
  }
  const unload = (e: BeforeUnloadEvent) => {
    if (saveState.value !== '已保存到此浏览器' || busy.value) {
      e.preventDefault()
      e.returnValue = ''
    }
  }
  window.addEventListener('beforeunload', unload)
  void fetchPublicMeta()
    .then((value) => {
      if (!disposed) meta.value = value
    })
    .catch(() => {
      feedback.value = '模型列表暂时不可用，本地编辑仍可使用。'
    })
  void loadImages()
  for (const r of project.value.runs)
    if (!r.jobId && ['submitting', 'preparing'].includes(r.status))
      r.status = 'unknown'
  schedulePoll()
  if (project.value.cloudEnabled) {
    cloudState.value = '云端待同步'
    cloudTimer = setTimeout(() => {
      void sync()
    }, 5000)
  }
  onBeforeUnmount(() => {
    disposed = true
    clearTimeout(saveTimer)
    clearTimeout(pollTimer)
    clearTimeout(cloudTimer)
    window.removeEventListener('beforeunload', unload)
    for (const url of Object.values(urls.value)) URL.revokeObjectURL(url)
  })
  return {
    project,
    selected,
    urls,
    meta,
    feedback,
    saveState,
    cloudState,
    busy,
    canUndo,
    canRedo,
    pendingAssets,
    assertOwner,
    checkpoint,
    changed,
    flush,
    historyMove,
    loadImages,
    addImage,
    generate,
    retry,
    sync,
    stopSync,
  }
}
