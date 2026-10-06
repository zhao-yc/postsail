export const taskStates = {
  scheduled: '等待排期', queued: '等待执行', running: '执行中', needs_action: '需要人工操作',
  previewed: '预览完成', submitted: '平台已受理', published: '已公开发表', failed: '执行失败',
  unknown: '结果不确定', cancelled: '已取消'
}
export const taskStatusLabel = (status) => taskStates[status] || status
export function taskStatusType(status) {
  if (['published', 'previewed'].includes(status)) return 'success'
  if (status === 'failed') return 'danger'
  if (['unknown', 'needs_action'].includes(status)) return 'warning'
  return 'info'
}
export function safeTaskUrl(value) {
  try {
    if (!/^https?:\/\//i.test(value || '')) return ''
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && url.hostname ? url.href : ''
  } catch { return '' }
}
export function resolutionError(task, data) {
  if (!data.note?.trim()) return '请填写平台核查说明'
  if (data.platform_url && !safeTaskUrl(data.platform_url)) return '请填写有效的 HTTP/HTTPS 平台链接'
  if (task.status === 'submitted' && (data.resolution !== 'published' || !safeTaskUrl(data.platform_url))) return '已受理任务须用公开文章链接确认已发表'
  return ''
}
// 初次打开只建立基线；提醒编号是持久化事件编号，已读、重试不会重复提示旧事件。
export function notificationPlan(cursor, data) {
  const latest = data.latest_id || 0
  if (cursor === null || latest < cursor) return { cursor: latest, items: [] }
  return { cursor: latest, items: (data.items || []).filter((item) => item.notification_id > cursor) }
}
