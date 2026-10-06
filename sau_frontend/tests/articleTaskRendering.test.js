// 在内存中渲染真实 Vue 组件，并验证通知副作用；不启动服务器或连接平台。
import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus, { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = await mkdtemp(resolve(root, 'node_modules/.task-center-test-'))
after(() => rm(output, { recursive: true, force: true }))
const stored = new Map()
const notices = []
let permissionRequests = 0
globalThis.localStorage = { getItem: (key) => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) }
globalThis.Notification = class {
  static permission = 'default'
  static async requestPermission() { permissionRequests++; this.permission = 'granted'; return this.permission }
  constructor(title, options) { notices.push({ title, options }) }
}
await build({
  root, configFile: false, envDir: false, logLevel: 'error', plugins: [vue()],
  resolve: { alias: { '@': resolve(root, 'src') } },
  build: { ssr: true, outDir: output, rollupOptions: { input: {
    center: resolve(root, 'src/views/ArticleTaskCenter.vue'),
    actions: resolve(root, 'src/components/articles/ArticleTaskActions.vue'),
    alerts: resolve(root, 'src/composables/useArticleTaskAlerts.js'),
    api: resolve(root, 'src/api/articles.js')
  } } }
})
const Page = (await import(pathToFileURL(resolve(output, 'center.js')))).default
const Actions = (await import(pathToFileURL(resolve(output, 'actions.js')))).default
const { useArticleTaskAlerts } = await import(pathToFileURL(resolve(output, 'alerts.js')))
const { articlesApi } = await import(pathToFileURL(resolve(output, 'api.js')))

async function render(component, props = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/article-tasks', component: Page }] })
  await router.push('/article-tasks')
  const app = createSSRApp({ render: () => h(component, props) })
  app.use(router).use(ElementPlus)
  app.provide(ID_INJECTION_KEY, { prefix: 100, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  return renderToString(app)
}
test('任务中心可渲染筛选与提醒入口', async () => {
  const html = await render(Page)
  for (const label of ['任务中心', '未读提醒', '原稿标题', '任务状态', '浏览器桌面提醒']) assert.ok(html.includes(label))
})
test('未知结果提供人工核查，禁止显示重试入口', async () => {
  const html = await render(Actions, { task: { id: 'unknown', title: '测试', status: 'unknown', retry_allowed: false, account_exists: true, article_id: 'draft', account_id: 1 } })
  assert.ok(html.includes('记录人工核查'))
  assert.ok(!html.includes('重试此账号'))
})
test('提交前失败允许重试，移除的账号没有登录入口', async () => {
  const html = await render(Actions, { task: { id: 'failed', title: '测试', status: 'failed', retry_allowed: true, account_exists: false, article_id: 'draft' } })
  assert.ok(html.includes('重试此账号'))
  assert.ok(!html.includes('账号登录'))
})
test('尚未执行的排期提供改期和取消入口', async () => {
  const html = await render(Actions, { task: { id: 'scheduled', title: '测试', status: 'scheduled', retry_allowed: false, cancel_allowed: true, reschedule_allowed: true, article_id: 'draft' } })
  assert.ok(html.includes('改期') && html.includes('取消发布'))
})
test('浏览器通知需显式启用，仅提示新事件，过期请求不覆盖状态', async () => {
  const alerts = useArticleTaskAlerts()
  let data = { latest_id: 1, unread: 1, items: [{ notification_id: 1, title: '旧任务', platform_label: '知乎', status: 'failed' }] }
  articlesApi.taskNotifications = async () => ({ data })
  await alerts.refresh()
  assert.equal(permissionRequests, 0)
  assert.equal(notices.length, 0)
  await alerts.setBrowserEnabled(true)
  assert.equal(permissionRequests, 1)
  await alerts.refresh()
  assert.equal(notices.length, 0)
  data = { latest_id: 2, unread: 2, items: [{ notification_id: 2, title: '新异常', platform_label: '知乎', status: 'unknown' }, ...data.items] }
  await alerts.refresh()
  assert.equal(notices.length, 1)
  await alerts.refresh()
  assert.equal(notices.length, 1)
  const pending = []
  articlesApi.taskNotifications = () => new Promise((done) => pending.push(done))
  const first = alerts.refresh()
  const second = alerts.refresh()
  pending[1]({ data: { latest_id: 4, unread: 4, items: [] } })
  pending[0]({ data: { latest_id: 3, unread: 3, items: [] } })
  await Promise.all([first, second])
  assert.equal(alerts.latestId.value, 4)
  assert.equal(alerts.unread.value, 4)
  // 其他窗口关闭通知偏好后，本窗口的后续轮询也停止桌面提示。
  stored.set('postsail.article-task-browser-notifications', 'false')
  articlesApi.taskNotifications = async () => ({ data: { latest_id: 5, unread: 5, items: [{ notification_id: 5, title: '新任务' }] } })
  await alerts.refresh()
  assert.equal(notices.length, 1)
  await alerts.setBrowserEnabled(false)
  assert.equal(alerts.browserEnabled.value, false)
})
