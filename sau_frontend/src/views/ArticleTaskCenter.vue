<template>
  <div class="task-center">
    <header class="workspace-header">
      <div><p class="kicker">内容发布 / 文章与图文</p><h1>任务中心</h1><p class="muted">集中查看所有原稿的发布进度，处理失败、人工验证和待核查结果。</p></div>
      <el-button :loading="loading" @click="refreshAll">刷新</el-button>
    </header>
    <div class="summary-grid">
      <button v-for="card in summaryCards" :key="card.status" type="button" :class="{ selected: filters.status === card.status }" @click="selectStatus(card.status)"><span>{{ card.label }}</span><strong>{{ card.count }}</strong></button>
    </div>

    <section class="notification-panel" aria-label="发布异常提醒">
      <div class="section-heading"><div><h2>未读提醒 <span>{{ unread }}</span></h2><p class="muted">查看或标记已读会保留任务记录；任务离开异常状态后，对应提醒自动结束。</p></div><el-button :disabled="!unread || reading" @click="readAll">全部已读</el-button></div>
      <el-alert v-if="notificationError" :title="notificationError" type="warning" :closable="false" />
      <div class="notification-list">
        <button v-for="item in notificationItems.slice(0, 6)" :key="item.notification_id" type="button" @click="openTask(item.id, item.notification_id)"><span class="unread-dot" /><div><strong>{{ item.title }}</strong><p>{{ item.platform_label }} · {{ item.account_name }} · {{ taskStatusLabel(item.status) }}</p><small>{{ item.notification_message || '请查看任务详情处理' }}</small></div><span>{{ formatTime(item.notification_created_at) }}</span></button>
        <p v-if="!unread && !notificationError" class="muted">暂无未读发布提醒。</p>
      </div>
      <el-button v-if="unread > 6" text type="primary" @click="showUnread">在任务列表查看全部未读提醒</el-button>
      <div class="browser-setting"><div><strong>浏览器桌面提醒</strong><p class="muted">{{ browserHint }} 工作台打开期间生效。</p></div><el-switch :model-value="browserEnabled && permission === 'granted'" :disabled="permission === 'unsupported'" :loading="changingPreference" aria-label="浏览器发布异常提醒" @change="toggleBrowser" /></div>
    </section>

    <section class="task-list-panel">
      <el-alert v-if="catalogError" :title="catalogError" type="warning" :closable="false" />
      <el-form class="filters" label-position="top" @submit.prevent="applyFilters">
        <el-form-item label="原稿标题"><el-input v-model="filters.q" clearable placeholder="搜索任务创建时的标题" @clear="applyFilters" /></el-form-item>
        <el-form-item label="平台"><el-select v-model="filters.platform" clearable placeholder="全部平台" @change="applyFilters"><el-option v-for="platform in platforms" :key="platform.platform" :label="platform.label" :value="platform.platform" /></el-select></el-form-item>
        <el-form-item label="账号"><el-select v-model="filters.account_id" clearable filterable placeholder="全部账号" @change="applyFilters"><el-option v-for="account in filterAccounts" :key="account.id" :label="`${account.user_name} · ${platformLabel(account.platform)}`" :value="account.id" /></el-select></el-form-item>
        <el-form-item label="任务状态"><el-select v-model="filters.status" @change="applyFilters"><el-option label="全部状态" value="" /><el-option label="需要处理" value="attention" /><el-option label="等待发布" value="pending" /><el-option v-for="(label, value) in taskStates" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="执行方式"><el-select v-model="filters.mode" clearable placeholder="全部方式" @change="applyFilters"><el-option label="正式发布" value="publish" /><el-option label="平台预览" value="preview" /></el-select></el-form-item>
        <el-form-item label="创建时间" class="date-filter"><el-date-picker v-model="dateRange" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" @change="applyFilters" /></el-form-item>
        <div class="filter-actions"><el-checkbox v-model="filters.unread" @change="applyFilters">仅未读提醒</el-checkbox><el-button native-type="submit" type="primary">查询</el-button><el-button @click="resetFilters">重置</el-button></div>
      </el-form>
      <el-alert v-if="listError" :title="listError" type="error" :closable="false" show-icon />
      <el-table v-loading="loading" :data="tasks" :empty-text="listError ? '任务加载失败，请刷新重试' : '当前条件下暂无任务'" row-key="id">
        <el-table-column label="内容" min-width="240"><template #default="{ row }"><button type="button" class="title-link" @click="openTask(row.id)"><span v-if="row.unread_notification_id" class="unread-dot" />{{ row.title }}</button><small>{{ row.mode === 'preview' ? '平台预览' : '正式发布' }} · 修订 {{ row.revision }}</small></template></el-table-column>
        <el-table-column label="平台与账号" min-width="170"><template #default="{ row }"><strong>{{ row.platform_label }}</strong><small>{{ row.account_name }} · #{{ row.account_id }}</small></template></el-table-column>
        <el-table-column label="状态" width="140"><template #default="{ row }"><el-tag :type="taskStatusType(row.status)">{{ taskStatusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="发布时间" min-width="235"><template #default="{ row }"><span>{{ formatSchedule(row) }}</span><small v-if="row.scheduled_at && Date.parse(row.scheduled_at) <= Date.now() && ['queued', 'scheduled'].includes(row.status)">已到期，等待执行</small></template></el-table-column>
        <el-table-column label="最近进度" min-width="220"><template #default="{ row }"><span>{{ row.message || '等待更新' }}</span><small>{{ formatTime(row.updated_at) }}</small></template></el-table-column>
        <el-table-column label="操作" width="155" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openTask(row.id)">查看／处理</el-button><el-button v-if="row.unread_notification_id" link :disabled="reading" @click="markRead(row.unread_notification_id)">已读</el-button></template></el-table-column>
      </el-table>
      <div class="pagination"><span class="muted">共 {{ total }} 个任务</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @size-change="page = 1; loadTasks()" @current-change="loadTasks" /></div>
    </section>

    <el-drawer v-model="detailVisible" title="任务详情" size="min(660px, 100vw)" :close-on-click-modal="!actionBusy" :close-on-press-escape="!actionBusy" :show-close="!actionBusy" @closed="closeDetail">
      <div v-loading="detailLoading" class="task-detail">
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" /><el-button v-if="detailError" @click="loadDetail(selectedId)">重新加载</el-button>
        <template v-if="selectedTask">
          <h2>{{ selectedTask.title }}</h2><p>{{ selectedTask.platform_label }} · {{ selectedTask.account_name }}</p><el-tag :type="taskStatusType(selectedTask.status)">{{ taskStatusLabel(selectedTask.status) }}</el-tag>
          <p class="progress-message">{{ selectedTask.message || '等待更新' }}</p>
          <dl><dt>执行方式</dt><dd>{{ selectedTask.mode === 'preview' ? '平台预览' : '正式发布' }}</dd><dt>计划时间</dt><dd>{{ formatSchedule(selectedTask) }}</dd><dt>内容修订</dt><dd>{{ selectedTask.revision }}（任务保存的内容）</dd><dt>执行次数</dt><dd>{{ selectedTask.attempts }}</dd><dt>创建时间</dt><dd>{{ formatTime(selectedTask.created_at) }}</dd><dt>更新时间</dt><dd>{{ formatTime(selectedTask.updated_at) }}</dd><dt>平台状态</dt><dd>{{ selectedTask.platform_status || '暂无' }}</dd><dt>任务编号</dt><dd class="task-id">{{ selectedTask.id }}</dd></dl>
          <el-alert v-if="selectedTask.stage === 'validation'" type="info" :closable="false" title="任务创建时未通过内容或账号校验。请在原稿或账号管理中修正，再重新提交。" />
          <el-alert v-if="selectedTask.status === 'needs_action'" type="warning" :closable="false" title="请按任务说明完成平台验证；确定未提交的任务可完成操作后重试。" />
          <el-alert v-if="selectedTask.status === 'unknown'" type="warning" :closable="false" title="先核对平台记录，再登记核查结果。确认未发布后才能重试。" />
          <ArticleTaskActions :key="selectedTask.id" :task="selectedTask" @changed="taskChanged" @busy="actionBusy = $event" />
          <section class="evidence-section"><h3>任务证据</h3><p v-if="!evidenceUrls.length" class="muted">暂无截图或回执文件。</p><template v-for="url in evidenceUrls" :key="url"><img v-if="/\.png(?:$|\?)/i.test(url)" :src="url" alt="本次任务的发布页面截图" /><el-link v-else :href="url" target="_blank" rel="noopener noreferrer">打开证据文件</el-link></template></section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { articlesApi, articleUrl } from '@/api/articles'
import { formatSchedule } from '@/utils/articleSchedule'
import { taskStates, taskStatusLabel, taskStatusType } from '@/utils/articleTasks'
import { useArticleTaskAlerts } from '@/composables/useArticleTaskAlerts'
import ArticleTaskActions from '@/components/articles/ArticleTaskActions.vue'

const route = useRoute()
const router = useRouter()
const alerts = useArticleTaskAlerts()
const { unread, items: notificationItems, error: notificationError, browserEnabled, permission } = alerts
const filters = reactive({ q: '', platform: '', account_id: '', status: typeof route.query.status === 'string' ? route.query.status : '', mode: '', unread: false })
const dateRange = ref(null)
const platforms = ref([])
const accounts = ref([])
const catalogError = ref('')
const filterAccounts = computed(() => accounts.value.filter((account) => !filters.platform || account.platform === filters.platform))
const platformLabel = (platform) => platforms.value.find((item) => item.platform === platform)?.label || platform
const page = ref(1)
const pageSize = ref(20)
const tasks = ref([])
const total = ref(0)
const summary = ref({ total: 0, attention: 0, pending: 0, running: 0 })
const summaryCards = computed(() => [{ label: '全部任务', status: '', count: summary.value.total }, { label: '需要处理', status: 'attention', count: summary.value.attention }, { label: '等待执行', status: 'pending', count: summary.value.pending }, { label: '执行中', status: 'running', count: summary.value.running }])
const loading = ref(false)
const listError = ref('')
const reading = ref(false)
const changingPreference = ref(false)
const browserHint = computed(() => permission.value === 'unsupported' ? '当前浏览器不支持桌面提醒。' : permission.value === 'denied' ? '浏览器已拒绝通知权限，请在浏览器设置中允许。' : '启用后，在产生新的发布异常时提醒。')
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const selectedId = ref('')
const selectedTask = ref(null)
const actionBusy = ref(false)
const evidenceUrls = computed(() => (selectedTask.value?.evidence || []).filter((path) => typeof path === 'string' && path.startsWith(`/api/article-publish-tasks/${selectedTask.value.id}/evidence/`)).map(articleUrl))
let listSequence = 0
let detailSequence = 0
let timer = null
let disposed = false
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无' }
async function loadTasks() {
  const sequence = ++listSequence
  loading.value = true
  const params = { ...filters, unread: filters.unread ? '1' : '0', page: page.value, page_size: pageSize.value }
  if (dateRange.value?.length === 2) { params.created_from = dateRange.value[0].toISOString(); params.created_before = dateRange.value[1].toISOString() }
  try {
    const response = await articlesApi.tasks(params)
    if (sequence !== listSequence || disposed) return
    tasks.value = response.data.items
    total.value = response.data.total
    summary.value = response.data.summary
    listError.value = ''
    const lastPage = Math.max(1, Math.ceil(total.value / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; await loadTasks() }
  } catch { if (sequence === listSequence && !disposed) listError.value = '任务列表加载失败，请检查筛选条件后刷新。' }
  finally { if (sequence === listSequence) loading.value = false }
}
function applyFilters() {
  page.value = 1
  if (filters.platform && !filterAccounts.value.some((account) => account.id === filters.account_id)) filters.account_id = ''
  if ((route.query.status || '') !== filters.status) router.replace({ query: { ...route.query, status: filters.status || undefined } })
  loadTasks()
}
function selectStatus(status) { filters.status = status; applyFilters() }
function showUnread() { filters.unread = true; selectStatus('attention') }
function resetFilters() { Object.assign(filters, { q: '', platform: '', account_id: '', status: '', mode: '', unread: false }); dateRange.value = null; applyFilters() }
async function loadDetail(id) {
  const sequence = ++detailSequence
  detailLoading.value = true
  detailError.value = ''
  try {
    const response = await articlesApi.task(id)
    if (sequence !== detailSequence || disposed) return
    selectedTask.value = response.data
    const notificationId = Number(route.query.notification)
    if (notificationId && notificationId === selectedTask.value.unread_notification_id) await markRead(notificationId)
  } catch { if (sequence === detailSequence && !disposed) detailError.value = '任务详情加载失败，请重新加载。' }
  finally { if (sequence === detailSequence) detailLoading.value = false }
}
function openTask(id, notificationId) { router.replace({ query: { ...route.query, task: id, notification: notificationId || undefined } }) }
function closeDetail() { if (detailVisible.value) return; detailSequence++; selectedTask.value = null; router.replace({ query: { ...route.query, task: undefined, notification: undefined } }) }
async function markRead(id) {
  if (reading.value) return
  reading.value = true
  try { await articlesApi.readTaskNotification(id); await Promise.all([alerts.refresh(), loadTasks()]); if (selectedTask.value?.unread_notification_id === id) selectedTask.value.unread_notification_id = null }
  catch { /* 接口显示失败，保留未读状态。 */ }
  finally { reading.value = false }
}
async function readAll() {
  if (reading.value || !alerts.latestId.value) return
  const throughId = alerts.latestId.value
  reading.value = true
  try { await articlesApi.readTaskNotifications(throughId); await Promise.all([alerts.refresh(), loadTasks()]); ElMessage.success('提醒已标记为已读，任务状态保留') }
  catch { /* 并发产生的新提醒不在本次已读范围内。 */ }
  finally { reading.value = false }
}
async function toggleBrowser(enabled) {
  changingPreference.value = true
  try { await alerts.setBrowserEnabled(enabled); if (enabled && !browserEnabled.value) ElMessage.info('浏览器未授予通知权限，站内提醒仍可查看') }
  finally { changingPreference.value = false }
}
async function taskChanged(id) { await Promise.all([loadTasks(), alerts.refresh(), selectedId.value === id ? loadDetail(id) : Promise.resolve()]) }
async function loadOptions() {
  const results = await Promise.allSettled([articlesApi.capabilities(), articlesApi.accounts()])
  if (disposed) return
  if (results[0].status === 'fulfilled') platforms.value = results[0].value.data.platforms
  if (results[1].status === 'fulfilled') accounts.value = results[1].value.data
  catalogError.value = results.some((result) => result.status === 'rejected') ? '部分平台或账号筛选选项加载失败，请刷新重试。' : ''
}
async function refreshAll() { await Promise.all([loadTasks(), alerts.refresh(), loadOptions(), detailVisible.value ? loadDetail(selectedId.value) : Promise.resolve()]) }
watch(() => route.query.status, (value) => { const status = typeof value === 'string' ? value : ''; if (filters.status !== status) { filters.status = status; page.value = 1; loadTasks() } })
watch(() => [route.query.task, route.query.notification], ([id]) => {
  if (typeof id !== 'string' || !id) { detailVisible.value = false; detailSequence++; return }
  if (selectedId.value !== id) actionBusy.value = false
  selectedId.value = id
  selectedTask.value = null
  detailVisible.value = true
  loadDetail(id)
}, { immediate: true })
onMounted(async () => {
  await Promise.all([loadOptions(), loadTasks()])
  if (disposed) return
  timer = window.setInterval(() => {
    if (document.hidden || disposed) return
    if (!loading.value) loadTasks()
    if (detailVisible.value && !detailLoading.value && !actionBusy.value) loadDetail(selectedId.value)
  }, 15000)
})
onBeforeUnmount(() => { disposed = true; listSequence++; detailSequence++; window.clearInterval(timer) })
</script>
<style scoped>
.task-center { max-width: 1600px; margin: 0 auto; color: #34445c; }
.workspace-header, .section-heading { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.workspace-header { margin-bottom: 24px; }
.workspace-header h1 { margin: 0 0 10px; font-size: 27px; font-weight: 600; }
.kicker { margin: 0 0 10px; color: #8a96a8; font-size: 12px; }
.muted { color: #7d899b; font-size: 13px; line-height: 1.7; margin: 6px 0; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 22px; }
.summary-grid button { display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding: 20px; border: 1px solid #e5eaf1; border-radius: 8px; background: #fff; color: #7d899b; cursor: pointer; }
.summary-grid button.selected { border-color: #409eff; background: #f3f8ff; }
.summary-grid strong { font-size: 28px; color: #34445c; font-weight: 600; }
.notification-panel, .task-list-panel { background: #fff; border: 1px solid #e5eaf1; border-radius: 8px; padding: 22px; margin-bottom: 22px; }
.section-heading { margin-bottom: 15px; }
.section-heading h2 { margin: 0; font-size: 17px; }
.section-heading h2 span { margin-left: 8px; color: #d88b38; }
.notification-list > button { display: flex; align-items: flex-start; text-align: left; gap: 12px; width: 100%; padding: 14px 0; background: transparent; border: 0; border-bottom: 1px solid #edf0f4; cursor: pointer; color: #34445c; }
.notification-list > button:hover { background: #f7faff; }
.notification-list > button > div { flex: 1; min-width: 0; }
.notification-list strong { display: block; overflow-wrap: anywhere; }
.notification-list p { font-size: 12px; color: #7d899b; margin: 6px 0; }
.notification-list small, .notification-list > button > span:last-child { color: #8995a6; font-size: 12px; line-height: 1.6; }
.unread-dot { width: 7px; height: 7px; border-radius: 50%; background: #e6a23c; display: inline-block; flex-shrink: 0; margin: 5px 7px 0 0; }
.browser-setting { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-top: 18px; }
.browser-setting strong { font-size: 13px; }
.filters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0 16px; }
.filters :deep(.el-select), .filters :deep(.el-date-editor) { width: 100%; }
.date-filter { grid-column: span 2; }
.filter-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; grid-column: 1 / -1; margin-bottom: 20px; }
.filter-actions :deep(.el-button) { margin-left: 0; }
.task-list-panel :deep(.el-table) { margin-top: 12px; }
.task-list-panel :deep(.el-table small) { display: block; color: #8b97a8; font-size: 12px; margin-top: 6px; }
.task-list-panel :deep(.el-table strong) { font-weight: 500; }
.title-link { border: 0; padding: 0; background: transparent; color: #326db3; font-size: 14px; text-align: left; line-height: 1.6; cursor: pointer; }
.pagination { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-top: 20px; flex-wrap: wrap; }
.task-detail h2 { font-size: 22px; line-height: 1.6; margin: 0; overflow-wrap: anywhere; }
.task-detail p { line-height: 1.7; }
.progress-message { background: #f5f7fa; padding: 14px; border-radius: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
.task-detail dl { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 13px 16px; font-size: 13px; line-height: 1.6; margin: 24px 0; }
.task-detail dt { color: #8b97a8; }
.task-detail dd { margin: 0; overflow-wrap: anywhere; }
.task-id { font-family: monospace; }
.task-detail :deep(.el-alert) { margin-bottom: 18px; }
.evidence-section { border-top: 1px solid #edf0f4; margin-top: 25px; padding-top: 15px; }
.evidence-section h3 { font-size: 15px; }
.evidence-section img { display: block; width: 100%; height: auto; margin: 12px 0; border: 1px solid #edf0f4; }
.evidence-section :deep(.el-link) { display: flex; justify-content: flex-start; margin: 12px 0; }
@media (max-width: 1100px) { .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 750px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } .summary-grid button { padding: 15px; } .notification-panel, .task-list-panel { padding: 16px; } .section-heading { align-items: flex-start; } .notification-list > button > span:last-child { display: none; } .filters { grid-template-columns: 1fr; } .date-filter { grid-column: auto; } .pagination :deep(.el-pagination) { flex-wrap: wrap; row-gap: 10px; } }
</style>
