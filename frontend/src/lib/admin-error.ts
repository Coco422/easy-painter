const fieldLabels: Record<string, string> = {
  username: '用户名',
  email: '邮箱',
  password: '密码',
  display_name: '显示名称',
}

export function adminErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail.trim() || fallback
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item: unknown) => {
      if (!item || typeof item !== 'object') return []
      const error = item as { loc?: unknown; msg?: unknown; type?: unknown }
      const field = Array.isArray(error.loc) ? error.loc[error.loc.length - 1] : undefined
      if (field === 'username' && ['string_pattern_mismatch', 'string_too_short', 'string_too_long'].includes(String(error.type))) {
        return ['用户名须为 2–64 位字母、数字或下划线；邮箱请填写到邮箱栏。']
      }
      if (field === 'password' && ['string_too_short', 'string_too_long'].includes(String(error.type))) {
        return ['密码长度须为 6–128 个字符。']
      }
      if (typeof error.msg !== 'string' || !error.msg.trim()) return []
      const label = typeof field === 'string' ? fieldLabels[field] ?? field : ''
      return [`${label ? `${label}：` : ''}${error.msg.replace(/^Value error,\s*/i, '')}`]
    })
    return [...new Set(messages)].join(' ') || fallback
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}
