import { ref } from 'vue'
import { articlesApi } from '@/api/articles'
import { notificationPlan, taskStatusLabel } from '@/utils/articleTasks'

const preferenceKey = 'postsail.article-task-browser-notifications'
const cursorKey = 'postsail.article-task-notification-cursor'
function readStorage(key) { try { return localStorage.getItem(key) } catch { return null } }
function writeStorage(key, value) { try { localStorage.setItem(key, String(value)) } catch { /* 禁用存储时仍支持本次会话。 */ } }
const storedCursor = readStorage(cursorKey)
let cursor = storedCursor !== null && /^\d+$/.test(storedCursor) ? Number(storedCursor) : null
const browserEnabled = ref(readStorage(preferenceKey) === 'true')
const unread = ref(0)
const items = ref([])
const latestId = ref(0)
const error = ref('')
const permission = ref(typeof Notification === 'undefined' ? 'unsupported' : Notification.permission)
let sequence = 0
let timer = null
let running = false
let navigate = () => {}

async function refresh() {
  const current = ++sequence
  try {
    const response = await articlesApi.taskNotifications({ page_size: 50 })
    if (current !== sequence) return
    const data = response.data
    unread.value = data.unread
    items.value = data.items
    latestId.value = data.latest_id
    error.value = ''
    const preference = readStorage(preferenceKey)
    if (preference !== null) browserEnabled.value = preference === 'true'
    if (typeof Notification !== 'undefined') permission.value = Notification.permission
    // 同源其他窗口可能已经显示提醒，先读取它们推进的游标。
    const stored = readStorage(cursorKey)
    if (stored !== null && /^\d+$/.test(stored)) cursor = Number(stored)
    const plan = notificationPlan(cursor, data)
    cursor = plan.cursor
    writeStorage(cursorKey, cursor)
    if (browserEnabled.value && permission.value === 'granted' && plan.items.length) {
      const first = plan.items[0]
      try {
        const notice = new Notification('PostSail · 发布任务需要处理', {
          body: plan.items.length === 1 ? `${first.title} · ${first.platform_label} · ${taskStatusLabel(first.status)}` : `${plan.items.length >= 50 ? '至少 ' : ''}${plan.items.length} 条新的发布异常，点击查看任务中心`,
          tag: `postsail-article-task-${data.latest_id}`
        })
        notice.onclick = () => { window.focus(); navigate(first.id, first.notification_id); notice.close() }
      } catch { /* 浏览器可能禁止通知构造；站内提醒仍保留。 */ }
    }
  } catch {
    if (current === sequence) error.value = '发布提醒暂时无法更新，请刷新重试。'
  }
}
async function tick() {
  await refresh()
  if (running) timer = window.setTimeout(tick, 15000)
}
function start(onNavigate) {
  navigate = onNavigate
  if (running) return
  running = true
  tick()
}
function stop() { running = false; sequence++; window.clearTimeout(timer) }
async function setBrowserEnabled(enabled) {
  if (!enabled) { browserEnabled.value = false; writeStorage(preferenceKey, false); return }
  if (typeof Notification === 'undefined') return
  try { permission.value = await Notification.requestPermission() }
  catch { permission.value = Notification.permission }
  browserEnabled.value = permission.value === 'granted'
  writeStorage(preferenceKey, browserEnabled.value)
  // 显式启用时从当前已观察到的位置开始，不把旧提醒集中弹出。
  cursor = latestId.value
  writeStorage(cursorKey, cursor)
}

export function useArticleTaskAlerts() {
  return { unread, items, latestId, error, browserEnabled, permission, refresh, start, stop, setBrowserEnabled }
}
