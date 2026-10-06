<template>
  <div class="task-actions">
    <el-button v-if="task.reschedule_allowed" :disabled="busy" @click="openSchedule">改期</el-button>
    <el-button v-if="task.cancel_allowed" type="danger" plain :disabled="busy" @click="cancelTask">取消发布</el-button>
    <el-button v-if="task.retry_allowed" type="primary" :disabled="busy" @click="retryTask">{{ task.status === 'needs_action' ? '完成操作后重试' : '重试此账号' }}</el-button>
    <el-button v-if="['unknown', 'submitted'].includes(task.status)" type="warning" plain :disabled="busy" @click="openResolution">{{ task.status === 'submitted' ? '核对公开发表' : '记录人工核查' }}</el-button>
    <el-button v-if="task.account_exists" :disabled="busy" @click="router.push({ path: '/account-management', query: { account_id: task.account_id } })">账号登录</el-button>
    <el-button :disabled="busy" @click="router.push({ path: '/articles', query: { article_id: task.article_id } })">打开原稿</el-button>
    <el-link v-if="safeTaskUrl(task.platform_url)" :href="safeTaskUrl(task.platform_url)" target="_blank" rel="noopener noreferrer">平台内容</el-link>
  </div>
  <el-dialog v-model="scheduleVisible" title="修改发布时间" width="min(480px, calc(100vw - 24px))" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
    <p>{{ editingTask?.title }} · {{ editingTask?.account_name }}</p>
    <p class="muted">改期保留任务创建时的内容。</p>
    <PublicationSchedule v-model="editedSchedule" :disabled="busy" />
    <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" />
    <template #footer><el-button :disabled="busy" @click="scheduleVisible = false">返回</el-button><el-button type="primary" :loading="busy" @click="saveSchedule">保存排期</el-button></template>
  </el-dialog>
  <el-dialog v-model="resolutionVisible" :title="editingTask?.status === 'submitted' ? '核对公开发表' : '记录人工核查'" width="min(540px, calc(100vw - 24px))" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
    <el-alert type="warning" :closable="false" :title="editingTask?.status === 'submitted' ? '请核对公开文章并填写链接和说明。平台已受理的任务只能确认已公开发表。' : '先到平台核查是否已有内容。结果不确定的任务不会自动重发。'" />
    <el-form label-position="top" class="resolution-form">
      <el-form-item label="核查结果"><el-select v-model="resolution.resolution" :disabled="busy"><el-option v-if="editingTask?.status === 'unknown'" label="确认没有发布，可以重试" value="not_published" /><el-option v-if="editingTask?.status === 'unknown'" label="平台已受理，正在审核" value="submitted" /><el-option label="确认已经公开发表" value="published" /></el-select></el-form-item>
      <el-form-item label="平台文章链接" :required="editingTask?.status === 'submitted'"><el-input v-model="resolution.platform_url" placeholder="http:// 或 https:// 公开文章链接" :disabled="busy" /></el-form-item>
      <el-form-item label="核查说明" required><el-input v-model="resolution.note" type="textarea" :rows="3" :disabled="busy" placeholder="记录核查过程与实际结果" /></el-form-item>
    </el-form>
    <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" />
    <template #footer><el-button :disabled="busy" @click="resolutionVisible = false">返回</el-button><el-button type="primary" :loading="busy" @click="saveResolution">保存核查结果</el-button></template>
  </el-dialog>
</template>
<script setup>
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { articlesApi } from '@/api/articles'
import { defaultSchedule, scheduleForTask, schedulePayload } from '@/utils/articleSchedule'
import { resolutionError, safeTaskUrl } from '@/utils/articleTasks'
import PublicationSchedule from './PublicationSchedule.vue'

const props = defineProps({ task: { type: Object, required: true } })
const emit = defineEmits(['changed', 'busy'])
const router = useRouter()
const busy = ref(false)
watch(busy, (value) => emit('busy', value))
const editingTask = ref(null)
const scheduleVisible = ref(false)
const editedSchedule = ref(defaultSchedule())
const resolutionVisible = ref(false)
const resolution = reactive({ resolution: '', platform_url: '', note: '' })
const actionError = ref('')
async function execute(operation, message) {
  if (busy.value) return false
  busy.value = true
  actionError.value = ''
  try { await operation(); ElMessage.success(message); return true }
  catch (error) { actionError.value = error.response?.data?.msg || error.message || '操作失败，请刷新任务后重试。'; return false }
  finally { busy.value = false; emit('changed', props.task.id) }
}
function openSchedule() {
  editingTask.value = { ...props.task }
  editedSchedule.value = scheduleForTask(props.task)
  actionError.value = ''
  scheduleVisible.value = true
}
async function saveSchedule() {
  let schedule
  try { schedule = schedulePayload(editedSchedule.value) }
  catch (error) { actionError.value = error.message; return }
  const task = editingTask.value
  if (await execute(() => articlesApi.reschedule(task.id, { schedule, expected_schedule_revision: task.schedule_revision }), '排期已更新')) scheduleVisible.value = false
}
async function cancelTask() {
  const task = { ...props.task }
  try { await ElMessageBox.confirm(`取消「${task.title}」向 ${task.account_name} 的发布？`, '取消发布', { confirmButtonText: '取消发布', cancelButtonText: '保留任务', type: 'warning' }) }
  catch { return }
  await execute(() => articlesApi.cancel(task.id, task.schedule_revision), '任务已取消')
}
async function retryTask() { const task = props.task; await execute(() => articlesApi.retry(task.id), '该账号任务已加入重试队列') }
function openResolution() {
  editingTask.value = { ...props.task }
  Object.assign(resolution, { resolution: props.task.status === 'submitted' ? 'published' : 'not_published', platform_url: safeTaskUrl(props.task.platform_url), note: '' })
  actionError.value = ''
  resolutionVisible.value = true
}
async function saveResolution() {
  const task = editingTask.value
  const data = { ...resolution, note: resolution.note.trim(), platform_url: resolution.platform_url.trim() }
  actionError.value = resolutionError(task, data)
  if (actionError.value) return
  if (await execute(() => articlesApi.resolve(task.id, data), '核查结果已记录')) resolutionVisible.value = false
}
</script>
<style scoped>
.task-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.task-actions :deep(.el-button) { margin-left: 0; }
.muted { color: #7d899b; font-size: 13px; }
.resolution-form { margin-top: 20px; }
.resolution-form :deep(.el-select) { width: 100%; }
</style>
