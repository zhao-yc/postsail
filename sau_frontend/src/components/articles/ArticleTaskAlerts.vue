<template>
  <el-badge :value="unread" :max="99" :hidden="!unread" class="task-alert-badge">
    <el-button text :type="error ? 'warning' : undefined" :title="error || '查看文章／图文发布任务'" @click="router.push({ path: '/article-tasks', query: { status: 'attention' } })">
      <el-icon><Bell /></el-icon><span>发布提醒</span>
    </el-button>
  </el-badge>
</template>
<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Bell } from '@element-plus/icons-vue'
import { useArticleTaskAlerts } from '@/composables/useArticleTaskAlerts'
const router = useRouter()
const { unread, error, start, stop } = useArticleTaskAlerts()
onMounted(() => start((id, notification) => router.push({ path: '/article-tasks', query: { task: id, notification } })))
onBeforeUnmount(stop)
</script>
<style scoped>
.task-alert-badge { margin-right: 10px; }
.task-alert-badge :deep(.el-icon) { margin-right: 6px; }
</style>
