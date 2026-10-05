// 时间按用户选择的时区解释，不能先用浏览器本地时区转换成 UTC。
export function defaultSchedule() {
  return { publish_at: '', timezone: 'Asia/Shanghai' }
}

export function schedulePayload(schedule) {
  if (!schedule?.publish_at || !schedule?.timezone) throw new Error('请为定时账号填写发布时间和时区')
  try { new Intl.DateTimeFormat('en-US', { timeZone: schedule.timezone }) }
  catch { throw new Error('请填写有效的 IANA 时区，例如 Asia/Shanghai') }
  return { publish_at: schedule.publish_at, timezone: schedule.timezone }
}

export function scheduleForTask(task) {
  const timezone = task.schedule_timezone || 'Asia/Shanghai'
  if (!task.scheduled_at) return { ...defaultSchedule(), timezone }
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  }).formatToParts(new Date(task.scheduled_at)).map(({ type, value }) => [type, value]))
  // 保留当前 UTC 偏移，夏令时回拨的时间也可原样读回；改选时间后由后端重新校验。
  const local = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`
  const offsetMinutes = Math.round((Date.parse(local + 'Z') - Date.parse(task.scheduled_at)) / 60000)
  const sign = offsetMinutes < 0 ? '-' : '+'
  const offset = Math.abs(offsetMinutes)
  const suffix = `${sign}${String(Math.floor(offset / 60)).padStart(2, '0')}:${String(offset % 60).padStart(2, '0')}`
  return { publish_at: local + suffix, timezone }
}

export function formatSchedule(task) {
  if (!task.scheduled_at) return '立即发布'
  const schedule = scheduleForTask(task)
  return `${schedule.publish_at.replace('T', ' ')} · ${schedule.timezone}`
}
