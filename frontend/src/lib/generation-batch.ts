/** Keep large batches bounded in memory and avoid sending a request flood. */
export function validGenerationCount(count: number): boolean {
  return Number.isSafeInteger(count) && count > 0
}

export async function submitGenerationBatch<T extends { credit_cost: number }>(
  count: number,
  submit: () => Promise<T>,
  options: {
    isCurrent: () => boolean
    shouldContinue?: () => boolean
    onSuccess: (result: T) => void
    onProgress?: (completed: number) => void
    wait?: () => Promise<void>
  },
) {
  if (!validGenerationCount(count)) throw new Error('生成数量需为正整数。')
  let accepted = 0, failed = 0, reserved = 0, error: Error | undefined
  const wait = options.wait ?? (() => new Promise<void>(resolve => setTimeout(resolve, 250)))
  for (let offset = 0; offset < count && options.isCurrent() && (options.shouldContinue?.() ?? true); offset += 4) {
    const results = await Promise.allSettled(Array.from({ length: Math.min(4, count - offset) }, submit))
    if (!options.isCurrent()) break
    for (const result of results) {
      if (result.status === 'fulfilled') {
        accepted++; reserved += result.value.credit_cost
        options.onSuccess(result.value)
      } else {
        failed++
        error ??= result.reason instanceof Error ? result.reason : new Error('提交失败，请稍后重试。')
      }
    }
    options.onProgress?.(accepted + failed)
    // Keep partial successes. Never keep submitting after a billing/auth/flood
    // refusal or an unknown outcome; retries must retain their original keys.
    if (failed) break
    if (offset + results.length < count && options.isCurrent() && (options.shouldContinue?.() ?? true)) await wait()
  }
  return { accepted, failed, reserved, remaining: count - accepted - failed, error }
}
