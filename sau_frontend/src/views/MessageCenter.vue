<template>
  <div class="message-workspace">
    <header class="workspace-header"><div><p class="kicker">运营 / 互动管理</p><h1>消息中心</h1><p class="description">查看平台评论和私信，统一回复、话术与自动回复设置。</p></div><div class="message-counters"><button type="button" @click="showState('unread')"><strong>{{ notifications.unreadCount ?? '—' }}</strong><span>未读消息</span></button><button type="button" @click="showState('unhandled')"><strong>{{ notifications.unhandledCount ?? '—' }}</strong><span>待处理</span></button></div></header>
    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" class="workspace-alert" />
    <el-tabs v-model="activeTab" @tab-change="changeTab"><el-tab-pane label="私信与评论" name="messages" /><el-tab-pane label="自动回复" name="rules" /><el-tab-pane label="账号管理" name="accounts" /><el-tab-pane label="话术库" name="phrases" /><el-tab-pane label="消息提醒" name="notifications" /></el-tabs>

    <template v-if="activeTab === 'messages'">
      <div class="filter-bar"><el-radio-group v-model="filters.kind" @change="filterChanged"><el-radio-button value="">全部</el-radio-button><el-radio-button value="comment">评论</el-radio-button><el-radio-button value="private">私信</el-radio-button></el-radio-group><el-select v-model="filters.platform" clearable placeholder="全部平台" @change="platformChanged"><el-option v-for="item in capabilities" :key="item.platform" :label="item.label" :value="item.platform" /></el-select><el-select v-model="filters.accountId" clearable filterable placeholder="全部账号" @change="filterChanged"><el-option v-for="account in filteredAccounts" :key="account.id" :label="account.name" :value="account.id" /></el-select><el-select v-model="filters.state" @change="filterChanged"><el-option label="全部状态" value="all" /><el-option label="未读" value="unread" /><el-option label="待处理" value="unhandled" /><el-option label="已处理" value="handled" /></el-select><el-input v-model="filters.q" placeholder="搜索消息或用户" clearable @clear="filterChanged" @keyup.enter="filterChanged"><template #append><el-button @click="filterChanged">搜索</el-button></template></el-input><el-button :loading="!!syncJob" :disabled="!syncableAccounts.length" @click="syncMessages">同步消息</el-button></div>
      <p class="sync-note">{{ syncText || '仅展示平台实际采集到的消息；平台能力和账号状态可在账号管理中查看。' }}</p>
      <div class="conversation-workspace">
        <aside class="message-rail" v-loading="loading"><div class="rail-heading"><span>消息列表</span><span>{{ total }} 条</span></div><div class="message-list"><button v-for="message in messages" :key="message.id" type="button" :class="['message-row', { selected: selectedId === message.id, unread: !message.read }]" @click="openMessage(message.id)"><div class="message-row-top"><strong>{{ message.authorName || '平台用户' }}</strong><span>{{ shortTime(message.createdAt) }}</span></div><p>{{ message.text || '（无文字内容）' }}</p><div class="message-row-meta"><span>{{ platformLabel(message.platform) }} · {{ kindLabel(message.kind) }} · {{ accountLabel(message.accountId) }}</span><el-tag v-if="message.handled" type="info" size="small">已处理</el-tag><span v-else class="unhandled-dot" title="待处理" /></div></button><el-empty v-if="!messages.length && !loading" :description="loadError ? '加载失败，请刷新重试' : filters.q || filters.platform || filters.accountId || filters.kind || filters.state !== 'all' ? '当前筛选条件下暂无匹配消息' : '暂无消息，请先同步已支持的账号'" :image-size="65" /></div><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" size="small" @current-change="loadMessages" /></aside>
        <section class="conversation-panel" v-loading="detailLoading">
          <el-empty v-if="!detail?.message" description="选择一条消息查看详情" :image-size="95" />
          <template v-else><div class="conversation-heading"><div><h2>{{ detail.message.authorName || '平台用户' }}</h2><span>{{ platformLabel(detail.message.platform) }} · {{ accountLabel(detail.message.accountId) }} · {{ kindLabel(detail.message.kind) }}</span></div><div class="conversation-actions"><el-button text :loading="marking" @click="markMessage({ read: !detail.message.read })">{{ detail.message.read ? '标为未读' : '标为已读' }}</el-button><el-button :type="detail.message.handled ? 'default' : 'primary'" plain :loading="marking" @click="markMessage({ handled: !detail.message.handled })">{{ detail.message.handled ? '重新待处理' : '标为已处理' }}</el-button></div></div><p v-if="detail.message.itemTitle" class="item-context">作品：{{ detail.message.itemTitle }}</p><div class="conversation-content"><article class="incoming-message"><div class="bubble-label">{{ detail.message.authorName || '平台用户' }} · {{ time(detail.message.createdAt) }}</div><p>{{ detail.message.text || '（无文字内容）' }}</p></article><article v-for="reply in detail.replies || []" :key="reply.id" class="outgoing-message"><div class="bubble-label">{{ reply.source === 'automatic' ? '自动回复' : '账号回复' }} · {{ time(reply.createdAt) }}<el-tag size="small" :type="replyType(reply.status)">{{ replyLabel(reply.status) }}</el-tag></div><p>{{ reply.text }}</p><small v-if="reply.error" class="reply-error">{{ reply.error }}</small><div v-if="reply.status === 'unknown'" class="resolve-actions"><span>先在平台核对实际发送情况</span><el-button size="small" :loading="resolving === reply.id" @click="resolveReply(reply, 'sent')">已确认发送</el-button><el-button size="small" :loading="resolving === reply.id" @click="resolveReply(reply, 'not_sent')">已确认未发送</el-button></div></article></div>
            <div class="reply-composer"><el-alert v-if="currentDraft.locked" type="warning" :closable="false" :title="currentDraft.lockReason || '发送结果待确认，请先核对回复记录和平台。'" /><el-alert v-else-if="replyIsUnverified(detail.message) && canReply(detail.message)" type="warning" :closable="false" title="该平台回复能力尚未用真实账号实测。点击发送会直接向平台提交回复，请核对目标和结果。" /><el-alert v-else-if="!canReply(detail.message)" type="info" :closable="false" :title="replyCapabilityReason(detail.message)" /><div class="composer-toolbar"><el-select v-model="selectedPhrase" clearable filterable placeholder="插入常用话术" :disabled="currentDraft.locked" @change="insertPhrase"><el-option v-for="phrase in phrases" :key="phrase.id" :label="phrase.name" :value="phrase.id" /></el-select><el-button text :loading="detailLoading" @click="reloadDetail">刷新回复记录</el-button><el-button v-if="currentDraft.locked && !(detail.replies || []).some(reply => reply.status === 'unknown' || reply.status === 'sending')" text type="warning" @click="clearLocalUncertainty">记录平台核查结果</el-button></div><el-input v-model="currentDraft.text" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="输入回复内容" :disabled="!canReply(detail.message) || currentDraft.locked || sending" /><div class="composer-footer"><span>回复会直接发送到 {{ platformLabel(detail.message.platform) }} 的 {{ accountLabel(detail.message.accountId) }}</span><el-button type="primary" :loading="sending" :disabled="!currentDraft.text.trim() || !canReply(detail.message) || currentDraft.locked" @click="sendReply">发送回复</el-button></div></div>
          </template>
        </section>
      </div>
    </template>

    <section v-else-if="activeTab === 'rules'" v-loading="loading"><div class="section-heading"><div><h2>自动回复策略</h2><p>仅对启用后新采集的消息生效；历史消息不会自动触发。</p></div><el-button type="primary" @click="editRule()">新建策略</el-button></div><el-table :data="rules" empty-text="暂无自动回复策略"><el-table-column label="策略" min-width="180"><template #default="{ row }"><strong>{{ row.name }}</strong><div class="muted">{{ ruleTypeLabel(row) }} · 优先级 {{ row.priority }}</div></template></el-table-column><el-table-column label="账号范围" min-width="190"><template #default="{ row }">{{ (row.accountIds || []).map(accountLabel).join('、') || '未选账号' }}</template></el-table-column><el-table-column label="触发条件" min-width="150"><template #default="{ row }">{{ row.trigger === 'keyword' ? (row.keywords || []).join('、') : '收到消息立即回复' }}</template></el-table-column><el-table-column prop="text" label="回复话术" min-width="240" show-overflow-tooltip /><el-table-column label="启用" width="90"><template #default="{ row }"><el-switch :model-value="row.enabled" :disabled="!row.enabled && !ruleCanEnable(row)" :loading="togglingRule === row.id" @change="toggleRule(row, $event)" /></template></el-table-column><el-table-column label="操作" width="125"><template #default="{ row }"><el-button link @click="editRule(row)">编辑</el-button><el-button link type="danger" @click="removeRule(row)">删除</el-button></template></el-table-column></el-table></section>

    <section v-else-if="activeTab === 'accounts'" v-loading="loading"><div class="section-heading"><div><h2>互动账号与平台能力</h2><p>沿用已有平台账号会话。发布账号支持不代表该平台的评论或私信已验证。</p></div><router-link to="/account-management"><el-button>管理平台账号</el-button></router-link></div><div class="capability-list"><div v-for="capability in capabilities" :key="capability.platform" class="capability-row"><strong>{{ capability.label }}</strong><span>{{ (capability.kinds || []).map(kindLabel).join('、') || '暂无互动能力' }}</span><el-tag :type="capability.status === 'available' ? 'success' : capability.status === 'unverified' ? 'warning' : 'info'" size="small">{{ capabilityLabel(capability.status) }}</el-tag><p>{{ capability.reason }}</p></div></div><el-table :data="accounts" empty-text="暂无平台账号，请到账号管理添加"><el-table-column prop="name" label="账号" min-width="180" /><el-table-column label="平台" width="115"><template #default="{ row }">{{ platformLabel(row.platform) }}</template></el-table-column><el-table-column label="登录状态" width="125"><template #default="{ row }"><el-tag :type="row.cookieAvailable && (row.status === 1 || row.status === 'valid' || row.status === 'active') ? 'success' : 'warning'">{{ row.cookieAvailable ? row.status === 0 || row.status === 'invalid' ? '需重新登录' : '会话已保存' : '缺少会话' }}</el-tag></template></el-table-column><el-table-column label="互动权限" min-width="240"><template #default="{ row }"><span>{{ accountInteractionHint(row) }}</span><small class="muted account-capability-note">{{ accountCapability(row)?.reason }}</small></template></el-table-column><el-table-column label="同步状态" min-width="180"><template #default="{ row }"><span>{{ syncStateLabel(row.syncState, row.lastSyncedAt) }}</span><small v-if="row.error" class="account-error">{{ row.error }}</small></template></el-table-column><el-table-column label="最近同步" min-width="170"><template #default="{ row }">{{ time(row.lastSyncedAt) }}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" :disabled="!accountCanSync(row) || !!syncJob" @click="syncMessages([row.id])">同步消息</el-button></template></el-table-column></el-table><div class="collection-settings"><div><h3>自动采集消息</h3><p>启用后按下列间隔采集指定账号；自动回复还需要单独启用对应策略。</p></div><el-switch :model-value="settings.enabled" :loading="savingSettings" active-text="已启用" inactive-text="已停用" @change="toggleCollection" /><el-form inline class="settings-form"><el-form-item label="采集账号"><el-select v-model="settingsForm.accountIds" multiple collapse-tags filterable placeholder="选择已支持账号"><el-option v-for="account in accounts" :key="account.id" :value="account.id" :label="account.name" :disabled="!accountCanSync(account)" /></el-select></el-form-item><el-form-item label="间隔（秒）"><el-input-number v-model="settingsForm.intervalSeconds" :min="60" :max="86400" /></el-form-item><el-form-item label="每小时回复上限"><el-input-number v-model="settingsForm.rateLimitPerHour" :min="1" :max="100" /></el-form-item><el-form-item><el-button :loading="savingSettings" @click="saveCollection">保存采集设置</el-button></el-form-item></el-form><p class="muted">最近运行 {{ time(settings.lastRunAt) }}<span v-if="settings.error"> · {{ settings.error }}</span></p></div></section>

    <section v-else-if="activeTab === 'phrases'" v-loading="loading"><div class="section-heading"><div><h2>话术库</h2><p>保存常用回复，发送前仍可编辑。</p></div><el-button type="primary" @click="editPhrase()">新增话术</el-button></div><el-table :data="phrases" empty-text="暂无话术"><el-table-column prop="name" label="名称" min-width="180" /><el-table-column prop="category" label="分类" min-width="120" /><el-table-column prop="text" label="话术内容" min-width="320" show-overflow-tooltip /><el-table-column label="操作" width="125"><template #default="{ row }"><el-button link @click="editPhrase(row)">编辑</el-button><el-button link type="danger" @click="removePhrase(row)">删除</el-button></template></el-table-column></el-table></section>

    <section v-else v-loading="loading"><div class="section-heading"><div><h2>消息提醒</h2><p>查看未读和待处理消息；浏览器提醒只在工作台打开期间生效。</p></div><el-button @click="refreshNotifications">刷新提醒</el-button></div><div class="notification-settings"><div><strong>工作台消息提醒</strong><p>更新顶部未读和待处理数量。</p></div><el-switch :model-value="settings.notifications?.enabled" :loading="savingSettings" @change="saveNotification('enabled', $event)" /></div><div class="notification-settings"><div><strong>浏览器桌面提醒</strong><p>{{ browserNotificationHint }}</p></div><el-switch :model-value="settings.notifications?.browser" :loading="savingSettings" :disabled="!browserNotificationsSupported" @change="enableBrowserNotifications" /></div><div class="notification-feed"><button v-for="message in notifications.items || []" :key="message.id" type="button" @click="openFromNotification(message)"><div><strong>{{ message.authorName || '平台用户' }}</strong><span>{{ platformLabel(message.platform) }} · {{ kindLabel(message.kind) }}</span></div><p>{{ message.text }}</p><small>{{ time(message.createdAt) }}</small></button><el-empty v-if="!(notifications.items || []).length" description="暂无待处理消息提醒" :image-size="75" /></div></section>

    <el-dialog v-model="localResolveDialog" title="记录平台核查结果" width="min(480px, calc(100vw - 32px))"><p class="description">先在平台确认本次回复是否存在，再选择实际核查结果。</p><el-radio-group v-model="localResolveOutcome" class="local-resolution"><el-radio value="sent">已在平台确认发送</el-radio><el-radio value="not_sent">已在平台确认未发送，且没有发送中的请求</el-radio></el-radio-group><template #footer><el-button @click="localResolveDialog = false">取消</el-button><el-button type="primary" :disabled="!localResolveOutcome" @click="saveLocalResolution">记录结果</el-button></template></el-dialog>
    <el-dialog v-model="ruleDialog" :title="ruleForm.id ? '编辑自动回复策略' : '新建自动回复策略'" width="min(620px, calc(100vw - 32px))" :close-on-click-modal="!savingRule"><el-form label-position="top"><el-form-item label="策略名称"><el-input v-model="ruleForm.name" maxlength="80" /></el-form-item><div class="form-row"><el-form-item label="回复场景"><el-select v-model="ruleForm.type" placeholder="选择回复场景" @change="ruleTypeChanged"><el-option label="评论回复" value="comment" /><el-option label="私信回复" value="private" /><el-option label="进入会话欢迎语" value="welcome" /></el-select></el-form-item><el-form-item label="平台"><el-select v-model="ruleForm.platform" placeholder="选择平台" @change="ruleForm.accountIds = []"><el-option v-for="item in capabilities" :key="item.platform" :label="item.label" :value="item.platform" :disabled="!rulePlatformAvailable(item)" /></el-select></el-form-item></div><el-form-item label="应用账号"><el-select v-model="ruleForm.accountIds" multiple filterable placeholder="选择账号"><el-option v-for="account in ruleAccounts" :key="account.id" :label="account.name" :value="account.id" :disabled="!accountCanReplyKind(account, ruleKind)" /></el-select></el-form-item><el-alert v-if="ruleForm.type === 'welcome'" type="info" :closable="false" title="欢迎语要求抖音官方应用的进入会话事件权限和回调配置；普通网页登录态不代表已授权。" /><div class="form-row"><el-form-item label="触发方式"><el-select v-model="ruleForm.trigger" placeholder="选择触发方式" :disabled="ruleForm.type === 'welcome'"><el-option label="收到后立即回复" value="immediate" /><el-option label="关键词匹配" value="keyword" /></el-select></el-form-item><el-form-item label="优先级"><el-input-number v-model="ruleForm.priority" :min="-100" :max="100" /></el-form-item></div><template v-if="ruleForm.trigger === 'keyword'"><el-form-item label="关键词（每行一个）"><el-input v-model="ruleKeywords" type="textarea" :rows="3" placeholder="咨询&#10;价格" /></el-form-item><el-form-item label="匹配方式"><el-radio-group v-model="ruleForm.matchMode"><el-radio value="any">包含任意关键词</el-radio><el-radio value="all">包含全部关键词</el-radio><el-radio value="exact">完全匹配</el-radio></el-radio-group></el-form-item></template><el-form-item label="回复内容"><el-input v-model="ruleForm.text" type="textarea" :rows="4" maxlength="1000" show-word-limit /></el-form-item><el-alert type="info" :closable="false" :title="ruleForm.id ? '编辑后保留当前启用状态；返回列表可显式启用或停用。' : '新建策略默认停用，保存后可在列表显式启用。'" /></el-form><template #footer><el-button :disabled="savingRule" @click="ruleDialog = false">取消</el-button><el-button type="primary" :loading="savingRule" @click="saveRule">保存策略</el-button></template></el-dialog>
    <el-dialog v-model="phraseDialog" :title="phraseForm.id ? '编辑话术' : '新增话术'" width="min(510px, calc(100vw - 32px))"><el-form label-position="top"><el-form-item label="名称"><el-input v-model="phraseForm.name" maxlength="80" /></el-form-item><el-form-item label="分类"><el-input v-model="phraseForm.category" maxlength="50" placeholder="例如：售前咨询" /></el-form-item><el-form-item label="话术内容"><el-input v-model="phraseForm.text" type="textarea" :rows="5" maxlength="1000" show-word-limit /></el-form-item></el-form><template #footer><el-button :disabled="savingPhrase" @click="phraseDialog = false">取消</el-button><el-button type="primary" :loading="savingPhrase" @click="savePhrase">保存话术</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { messagesApi } from "@/api/messages";
const activeTab = ref("messages"), filters = reactive({ platform: "", accountId: "", kind: "", q: "", state: "all" });
const capabilities = ref([]), accounts = ref([]), messages = ref([]), rules = ref([]), phrases = ref([]), notifications = ref({}), settings = ref({});
const settingsForm = reactive({ accountIds: [], intervalSeconds: 300, rateLimitPerHour: 20 });
const loading = ref(false), detailLoading = ref(false), loadError = ref(""), total = ref(0), page = ref(1), pageSize = 20, selectedId = ref(null), detail = ref(null), selectedPhrase = ref(null);
const marking = ref(false), sending = ref(false), resolving = ref(null), drafts = reactive({}), syncJob = ref(null), syncText = ref(""), savingSettings = ref(false), togglingRule = ref(null);
const ruleDialog = ref(false), savingRule = ref(false), ruleKeywords = ref(""), ruleForm = reactive({});
const phraseDialog = ref(false), savingPhrase = ref(false), phraseForm = reactive({});
const localResolveDialog = ref(false), localResolveOutcome = ref(""), localResolveMessageId = ref(null);
let alive = true, listVersion = 0, detailVersion = 0, tabVersion = 0, syncTimer = null, notificationTimer = null, notificationCount = null;
const emptyDraft = reactive({ text: "", key: "", locked: false, lockReason: "" });
const currentDraft = computed(() => drafts[selectedId.value] || emptyDraft);
const filteredAccounts = computed(() => accounts.value.filter((account) => !filters.platform || account.platform === filters.platform));
const syncableAccounts = computed(() => filteredAccounts.value.filter((account) => (!filters.accountId || account.id === filters.accountId) && accountCanSync(account, filters.kind || "all")));
const ruleKind = computed(() => ({ welcome: "welcome", private: "private", comment: "comment" })[ruleForm.type] || "comment");
const ruleAccounts = computed(() => accounts.value.filter((account) => account.platform === ruleForm.platform));
const browserNotificationsSupported = typeof window !== "undefined" && "Notification" in window;
const browserNotificationHint = computed(() => !browserNotificationsSupported ? "当前浏览器不支持桌面通知。" : Notification.permission === "denied" ? "浏览器已拒绝通知权限，请先在浏览器设置中允许。" : "启用时会向浏览器申请通知权限；有新增待处理消息时提醒。");
// 显示平台的中文名称。
function platformLabel(value) {
  return capabilities.value.find((item) => item.platform === value)?.label || value || "未知平台";
}
// 从真实账号列表读取显示名称。
function accountLabel(id) {
  return accounts.value.find((item) => item.id === id)?.name || `账号 ${id}`;
}
// 将平台消息类型转换为中文。
function kindLabel(kind) {
  return { comment: "评论", private: "私信", follow: "关注事件", welcome: "进入会话事件", all: "全部消息" }[kind] || kind;
}
// 优先显示后端中文错误；传输层英文摘要替换为操作相关的中文提示。
function frontendError(error, fallback) {
  const message = error.response?.data?.msg || error.response?.data?.message || error.message;
  return typeof message === "string" && /[\u4e00-\u9fff]/.test(message) ? message : fallback;
}
// 显示服务端返回的时间，缺少时间时给出明确状态。
function time(value) {
  if (!value) return "暂无记录";
  const text = String(value);
  if (/(?:Z|[+-]\d{2}:\d{2})$/.test(text)) {
    const parsed = new Date(text);
    if (!Number.isNaN(parsed.getTime())) return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(parsed);
  }
  return text.replace("T", " ").slice(0, 19);
}
// 显示列表需要的简短消息时间。
function shortTime(value) {
  return value ? time(value).slice(5, 16) : "";
}
// 显示能力是否可用、待验证或未接入。
// 显示平台同步状态，首次未采集与空闲状态分开。
function syncStateLabel(value, lastSyncedAt) {
  return value === "syncing" ? "同步中" : value === "idle" ? lastSyncedAt ? "空闲" : "尚未同步" : value === "failed" ? "同步失败" : "等待同步";
}
function capabilityLabel(status) {
  return { available: "可用", unverified: "待验证", unsupported: "暂不支持", needs_login: "需登录或官方授权" }[status] || status;
}
// 显示真实发送记录的状态，未知结果不会当作失败。
function replyLabel(status) {
  return { sent: "已发送", sending: "发送中", failed: "发送失败", unknown: "结果待确认", not_sent: "已确认未发送" }[status] || status;
}
// 为发送状态选择可辨认的提示颜色。
function replyType(status) {
  return status === "sent" ? "success" : ["unknown", "sending"].includes(status) ? "warning" : "danger";
}
// 按平台读取后端返回的能力定义。
function capabilityFor(platform) {
  return capabilities.value.find((item) => item.platform === platform);
}
// 账号级能力包含会话和官方授权状态，优先使用服务端真实检查结果。
function accountCapability(account) {
  return account?.capabilities || capabilityFor(account?.platform);
}
// 在账号表说明每种发送能力，普通登录会话与官方授权分开呈现。
function accountInteractionHint(account) {
  const cap = accountCapability(account);
  return Object.entries(cap?.operations || {}).map(([kind, operation]) => `${kindLabel(kind)}回复：${capabilityLabel(operation.reply)}`).join(" · ") || "暂无互动能力";
}
// 待实测的已实现操作允许用户显式验证，未接入或缺少登录配置的操作保持禁用。
function accountReady(account) {
  const cap = accountCapability(account);
  if (account.capabilities) return cap?.status !== "unsupported";
  return account.cookieAvailable && account.status !== 0 && account.status !== "invalid" && cap?.status !== "unsupported";
}
// 仅允许实际可轮询的消息类型参与采集。
function accountCanSync(account, kind = "all") {
  const cap = accountCapability(account);
  return accountReady(account) && (cap?.fetchableKinds || cap?.kinds || []).some((item) => (kind === "all" || item === kind) && operationAvailable(cap, item, "fetch"));
}
// 单独检查该消息类型的发送能力，不从发布能力推断。
function accountCanReplyKind(account, kind) {
  const cap = accountCapability(account);
  return accountReady(account) && (cap?.kinds || []).includes(kind) && operationAvailable(cap, kind, "reply");
}
// 未声明操作时默认禁止，不能用全局平台状态推断私信和评论具有同样能力。
function operationAvailable(cap, kind, operation) {
  const state = cap?.operations?.[kind]?.[operation];
  return state === true || ["available", "unverified"].includes(state);
}
// 识别已实现但尚未真实账号验证的发送操作。
function replyIsUnverified(message) {
  const account = accounts.value.find((item) => item.id === message.accountId);
  return accountCapability(account)?.operations?.[message.kind]?.reply === "unverified";
}
// 只允许已接入的入站评论或私信进行人工回复。
function canReply(message) {
  const account = accounts.value.find((item) => item.id === message.accountId);
  return !!account && accountCanReplyKind(account, message.kind) && message.direction === "inbound" && ["comment", "private"].includes(message.kind);
}
// 未开放回复时给出当前平台的真实限制。
function replyCapabilityReason(message) {
  if (message.kind === "welcome") return "进入会话事件仅由已启用的欢迎策略处理，不支持人工重复发送欢迎语。";
  const account = accounts.value.find((item) => item.id === message.accountId);
  const cap = accountCapability(account);
  return cap?.reason || "该账号或平台尚未验证当前消息类型的回复能力，请查看账号管理。";
}
// 规则可选平台必须具有对应事件和回复操作。
function rulePlatformAvailable(cap) {
  return cap.status !== "unsupported" && (cap.kinds || []).includes(ruleKind.value) && operationAvailable(cap, ruleKind.value, "reply");
}
// 启用策略前检查全部账号与平台能力。
function ruleCanEnable(rule) {
  const kind = { comment: "comment", private: "private", welcome: "welcome" }[rule.type];
  const selected = (rule.accountIds || []).map((id) => accounts.value.find((account) => account.id === id));
  return !!selected.length && selected.every((account) => account && accountCanReplyKind(account, kind));
}
// 显示自动回复策略的中文场景。
function ruleTypeLabel(rule) {
  return { comment: "评论回复", private: "私信回复", welcome: "进入会话欢迎语" }[rule.type] || rule.type;
}
// 生成每次手动回复的幂等键。
function uuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    return (char === "x" ? random : random & 3 | 8).toString(16);
  });
}
// 为每条消息保留独立回复草稿和发送观察状态。
function ensureDraft(id) {
  if (!drafts[id]) drafts[id] = { text: "", key: uuid(), locked: false, lockReason: "" };
  return drafts[id];
}
// 并行载入平台能力、账号归属和筛选候选。
async function loadMetadata() {
  const results = await Promise.allSettled([messagesApi.capabilities(), messagesApi.accounts(), messagesApi.phrases(), messagesApi.settings()]);
  if (!alive) return;
  if (results[0].status === "fulfilled") capabilities.value = results[0].value.data?.platforms || [];
  if (results[1].status === "fulfilled") accounts.value = results[1].value.data?.items || [];
  if (results[2].status === "fulfilled") phrases.value = results[2].value.data?.items || [];
  if (results[3].status === "fulfilled") applySettings(results[3].value.data || {});
  if (results.some((result) => result.status === "rejected")) loadError.value = "部分账号或配置加载失败，请刷新重试";
}
// 将后端消息设置复制到采集表单。
function applySettings(value) {
  settings.value = value;
  Object.assign(settingsForm, { accountIds: [...value.accountIds || []], intervalSeconds: value.intervalSeconds || 300, rateLimitPerHour: value.rateLimitPerHour || 20 });
}
// 列表请求使用序号防止旧的搜索结果覆盖新筛选，详情与列表分别控制。
async function loadMessages() {
  const version = ++listVersion;
  loading.value = true;
  loadError.value = "";
  messages.value = [];
  total.value = 0;
  try {
    const data = (await messagesApi.messages({ ...filters, page: page.value, pageSize })).data || {};
    if (!alive || version !== listVersion) return;
    messages.value = data.items || [];
    total.value = data.total || 0;
    notifications.value = { ...notifications.value, unreadCount: data.unreadCount, unhandledCount: data.unhandledCount };
  } catch (error) {
    if (alive && version === listVersion) loadError.value = frontendError(error, "消息加载失败");
  } finally {
    if (alive && version === listVersion) loading.value = false;
  }
}
// 载入所选消息详情，旧请求不能覆盖新选择。
async function openMessage(id) {
  const version = ++detailVersion;
  selectedId.value = id;
  detail.value = null;
  selectedPhrase.value = null;
  ensureDraft(id);
  detailLoading.value = true;
  try {
    const data = (await messagesApi.detail(id)).data;
    if (!alive || version !== detailVersion || selectedId.value !== id) return;
    detail.value = data;
    reconcileDraft(id, data);
  } catch (error) {
    if (alive && version === detailVersion) loadError.value = frontendError(error, "消息详情加载失败");
  } finally {
    if (alive && version === detailVersion) detailLoading.value = false;
  }
}
// 刷新当前消息的回复记录以确认真实发送状态。
async function reloadDetail() {
  if (selectedId.value) await openMessage(selectedId.value);
}
// 用发送记录恢复超时后的草稿状态，未知回复继续保持锁定。
function reconcileDraft(id, data) {
  const draft = ensureDraft(id), replies = data?.replies || [];
  if (replies.some((reply) => ["unknown", "sending"].includes(reply.status))) {
    draft.locked = true;
    draft.lockReason = "有发送中的回复或未确认结果，请先核查，避免重复发送。";
  } else if (draft.attemptedText && replies.some((reply) => reply.text === draft.attemptedText && Date.parse(reply.createdAt) >= draft.attemptedAt - 2e3 && reply.status === "sent")) {
    draft.locked = false;
    draft.text = "";
    draft.key = uuid();
    draft.lockReason = "";
    draft.attemptedText = "";
  } else if (draft.attemptedText && replies.some((reply) => reply.text === draft.attemptedText && Date.parse(reply.createdAt) >= draft.attemptedAt - 2e3 && reply.status === "failed")) {
    draft.locked = false;
    draft.key = uuid();
    draft.lockReason = "";
    draft.attemptedText = "";
  }
}
// 筛选改变时回到第一页并重新读取数据。
function filterChanged() {
  page.value = 1;
  selectedId.value = null;
  detail.value = null;
  detailVersion++;
  loadMessages();
}
// 切换平台时清除原平台的账号筛选。
function platformChanged() {
  filters.accountId = "";
  filterChanged();
}
// 从未读和待处理计数跳转到对应消息筛选。
function showState(state) {
  activeTab.value = "messages";
  filters.state = state;
  filterChanged();
}
// 按当前页签载入真实运营配置，防止旧页签请求污染页面。
async function changeTab() {
  const version = ++tabVersion;
  listVersion++;
  loading.value = true;
  loadError.value = "";
  try {
    if (activeTab.value === "messages") await loadMessages();
    else if (activeTab.value === "rules") {
      const response = await messagesApi.rules();
      if (version === tabVersion) rules.value = response.data?.items || [];
    } else if (activeTab.value === "phrases") {
      const response = await messagesApi.phrases();
      if (version === tabVersion) phrases.value = response.data?.items || [];
    } else if (activeTab.value === "accounts") await loadMetadata();
    else await refreshNotifications();
  } catch (error) {
    if (version === tabVersion) loadError.value = frontendError(error, "加载失败");
  } finally {
    if (version === tabVersion) loading.value = false;
  }
}
// 显式保存已读或已处理状态并更新提醒计数。
async function markMessage(state) {
  if (marking.value || !detail.value?.message) return;
  marking.value = true;
  const id = selectedId.value;
  try {
    await messagesApi.mark(id, state);
    if (detail.value?.message?.id === id) Object.assign(detail.value.message, state);
    const row = messages.value.find((item) => item.id === id);
    if (row) Object.assign(row, state);
    await refreshNotifications();
  } finally {
    marking.value = false;
  }
}
// 将常用话术插入当前草稿，仍需用户点击发送。
function insertPhrase(id) {
  const phrase = phrases.value.find((item) => item.id === id);
  if (phrase && !currentDraft.value.locked) currentDraft.value.text = currentDraft.value.text ? `${currentDraft.value.text}
${phrase.text}` : phrase.text;
  selectedPhrase.value = null;
}
// 幂等键在一次发送中保持不变；网络超时按结果未知锁定，不自动重发。
async function sendReply() {
  const message = detail.value?.message, draft = currentDraft.value;
  if (sending.value || !message || draft.locked || !draft.text.trim() || !canReply(message)) return;
  const id = message.id;
  draft.attemptedText = draft.text.trim();
  draft.attemptedAt = Date.now();
  sending.value = true;
  try {
    const reply = (await messagesApi.reply(id, { text: draft.text.trim(), idempotencyKey: draft.key })).data;
    if (reply?.status === "sent") {
      draft.text = "";
      draft.key = uuid();
      draft.locked = false;
      ElMessage.success("回复已发送");
    } else if (reply?.status === "failed") {
      draft.key = uuid();
      ElMessage.error(reply.error || "回复发送失败，可核对原因后重新发送");
    } else {
      draft.locked = true;
      draft.lockReason = reply?.error || "发送结果未确认，请先到平台核查。";
    }
    if (selectedId.value === id) await reloadDetail();
    await refreshNotifications();
  } catch (error) {
    const rejectedBeforeSending = [400, 401, 403, 404, 422].includes(error.response?.status);
    draft.locked = !rejectedBeforeSending;
    draft.lockReason = rejectedBeforeSending ? "" : "发送请求未得到确认。请刷新回复记录并核对平台，确认未发送后才可再次发送。";
    if (rejectedBeforeSending) {
      draft.key = uuid();
      draft.attemptedText = "";
    }
    loadError.value = frontendError(error, draft.lockReason || "回复请求被拒绝，请核对账号登录状态和内容");
  } finally {
    sending.value = false;
  }
}
// 用户完成平台核查后持久化未知发送结果。
async function resolveReply(reply, outcome) {
  if (resolving.value) return;
  const messageId = reply.messageId || selectedId.value;
  const draft = ensureDraft(messageId);
  try {
    await ElMessageBox.confirm(outcome === "sent" ? "确认已在平台看到这条回复，并记录为已发送？" : "确认已在平台核查这条回复未发送？记录后可重新编辑发送。", "记录人工核查", { confirmButtonText: "确认记录", cancelButtonText: "取消", type: "warning" });
  } catch {
    return;
  }
  resolving.value = reply.id;
  try {
    await messagesApi.resolve(reply.id, { outcome });
    draft.locked = false;
    draft.lockReason = "";
    draft.key = uuid();
    if (outcome === "sent") draft.text = "";
    if (selectedId.value === messageId) await reloadDetail();
    ElMessage.success("人工核查结果已记录");
  } finally {
    resolving.value = null;
  }
}
// 打开核查表单，保留未确认状态直到用户填写。
function clearLocalUncertainty() {
  localResolveMessageId.value = selectedId.value;
  localResolveOutcome.value = "";
  localResolveDialog.value = true;
}
// 仅解除当前浏览器的发送观察锁；平台未返回发送记录时仍需人工核查。
function saveLocalResolution() {
  const draft = ensureDraft(localResolveMessageId.value);
  if (!localResolveOutcome.value) return;
  draft.locked = false;
  draft.lockReason = "";
  draft.key = uuid();
  draft.attemptedText = "";
  if (localResolveOutcome.value === "sent") draft.text = "";
  localResolveDialog.value = false;
  ElMessage.success("本次核查结果已记录在当前会话");
}
// 仅用户点击同步才创建消息采集任务。
async function syncMessages(ids) {
  if (syncJob.value) return;
  const accountIds = Array.isArray(ids) ? ids : syncableAccounts.value.map((item) => item.id);
  if (!accountIds.length) return;
  syncText.value = "正在创建消息同步任务…";
  try {
    const job = (await messagesApi.sync({ accountIds, kind: activeTab.value === "accounts" ? "all" : filters.kind || "all" })).data;
    syncJob.value = job;
    await pollSync();
  } catch (error) {
    syncJob.value = null;
    syncText.value = frontendError(error, "消息同步失败");
  }
}
// 同步任务仅轮询同一任务；观察失败保留任务句柄，避免重复创建采集任务。
async function pollSync() {
  if (!alive || !syncJob.value?.id) return;
  try {
    const job = (await messagesApi.syncJob(syncJob.value.id)).data;
    if (!alive) return;
    syncJob.value = job;
    if (["completed", "failed", "done", "partial", "cancelled"].includes(job.status)) {
      syncText.value = (job.results || []).map((item) => `${accountLabel(item.accountId)} ${kindLabel(item.kind)}：${item.error || `${item.count || 0} 条`}`).join("；") || job.error || "同步任务已结束";
      syncJob.value = null;
      await Promise.all([loadMetadata(), loadMessages(), refreshNotifications()]);
      return;
    }
    syncText.value = "正在采集平台消息…";
  } catch (error) {
    syncText.value = `${frontendError(error, "暂时无法读取同步进度")}，继续观察当前任务。`;
  }
  if (alive) syncTimer = setTimeout(pollSync, 2500);
}
// 复制策略或创建默认停用的新策略表单。
function editRule(rule) {
  Object.assign(ruleForm, rule ? { ...rule, accountIds: [...rule.accountIds || []], kinds: [...rule.kinds || []] } : { id: null, name: "", platform: "", accountIds: [], kinds: ["comment"], type: "comment", trigger: "keyword", keywords: [], matchMode: "any", text: "", priority: 0, enabled: false });
  ruleKeywords.value = (rule?.keywords || []).join("\n");
  ruleDialog.value = true;
}
// 切换回复场景时清除不再适用的平台和账号。
function ruleTypeChanged() {
  ruleForm.kinds = [ruleKind.value];
  ruleForm.platform = "";
  ruleForm.accountIds = [];
  if (ruleForm.type === "welcome") ruleForm.trigger = "immediate";
}
// 校验并保存策略，新策略始终保持停用。
async function saveRule() {
  if (savingRule.value) return;
  const keywords = ruleKeywords.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
  if (!ruleForm.name.trim() || !ruleForm.text.trim() || !ruleForm.platform || !ruleForm.accountIds.length || ruleForm.trigger === "keyword" && !keywords.length) {
    ElMessage.warning("请填写名称、平台、账号、回复内容及关键词");
    return;
  }
  savingRule.value = true;
  try {
    const payload = { ...ruleForm, name: ruleForm.name.trim(), text: ruleForm.text.trim(), keywords, kinds: [ruleKind.value], enabled: ruleForm.id ? ruleForm.enabled : false };
    if (ruleForm.id) await messagesApi.updateRule(ruleForm.id, payload);
    else await messagesApi.createRule(payload);
    ruleDialog.value = false;
    await changeTab();
    ElMessage.success("策略已保存");
  } finally {
    savingRule.value = false;
  }
}
// 显式启用或停用策略，不在载入时执行自动发送。
async function toggleRule(rule, enabled) {
  if (togglingRule.value) return;
  if (enabled && !ruleCanEnable(rule)) {
    ElMessage.warning("策略所需的平台能力或账号登录状态尚不可用");
    return;
  }
  togglingRule.value = rule.id;
  try {
    await messagesApi.updateRule(rule.id, { enabled });
    rule.enabled = enabled;
    ElMessage.success(enabled ? "策略已启用，仅处理新采集消息" : "策略已停用");
  } finally {
    togglingRule.value = null;
  }
}
// 确认删除策略，仅删除运营配置。
async function removeRule(rule) {
  try {
    await ElMessageBox.confirm(`删除策略“${rule.name}”？`, "删除自动回复策略", { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" });
  } catch {
    return;
  }
  await messagesApi.deleteRule(rule.id);
  await changeTab();
}
// 复制常用话术到独立编辑表单。
function editPhrase(phrase) {
  Object.assign(phraseForm, phrase ? { ...phrase } : { id: null, name: "", text: "", category: "" });
  phraseDialog.value = true;
}
// 保存常用话术，空分类使用默认分类。
async function savePhrase() {
  if (savingPhrase.value) return;
  if (!phraseForm.name.trim() || !phraseForm.text.trim()) {
    ElMessage.warning("请填写话术名称和内容");
    return;
  }
  savingPhrase.value = true;
  try {
    const payload = { name: phraseForm.name.trim(), text: phraseForm.text.trim(), category: phraseForm.category.trim() || "常用话术" };
    if (phraseForm.id) await messagesApi.updatePhrase(phraseForm.id, payload);
    else await messagesApi.createPhrase(payload);
    phraseDialog.value = false;
    const response = await messagesApi.phrases();
    phrases.value = response.data?.items || [];
    ElMessage.success("话术已保存");
  } finally {
    savingPhrase.value = false;
  }
}
// 确认删除话术，不影响既有发送记录。
async function removePhrase(phrase) {
  try {
    await ElMessageBox.confirm(`删除话术“${phrase.name}”？`, "删除话术", { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" });
  } catch {
    return;
  }
  await messagesApi.deletePhrase(phrase.id);
  phrases.value = phrases.value.filter((item) => item.id !== phrase.id);
}
// 保存采集账号、间隔和频率上限。
async function saveCollection() {
  if (savingSettings.value) return;
  if (settings.value.enabled && !settingsForm.accountIds.length) {
    ElMessage.warning("启用自动采集需选择账号");
    return;
  }
  savingSettings.value = true;
  try {
    applySettings((await messagesApi.saveSettings({ ...settingsForm })).data);
    ElMessage.success("采集设置已保存");
  } finally {
    savingSettings.value = false;
  }
}
// 只有显式开关操作才启用后台采集。
async function toggleCollection(enabled) {
  if (savingSettings.value) return;
  if (enabled && !settingsForm.accountIds.length) {
    ElMessage.warning("请先选择自动采集账号并保存");
    return;
  }
  savingSettings.value = true;
  try {
    applySettings((await messagesApi.saveSettings({ ...settingsForm, enabled })).data);
    ElMessage.success(enabled ? "自动采集已启用" : "自动采集已停用");
  } finally {
    savingSettings.value = false;
  }
}
// 保存提醒偏好，不创建发送任务。
async function saveNotification(key, value) {
  if (savingSettings.value) return;
  savingSettings.value = true;
  try {
    applySettings((await messagesApi.saveSettings({ notifications: { ...settings.value.notifications || {}, [key]: value } })).data);
  } finally {
    savingSettings.value = false;
  }
}
// 在用户操作时请求浏览器通知权限。
async function enableBrowserNotifications(enabled) {
  if (!enabled) {
    await saveNotification("browser", false);
    return;
  }
  if (!browserNotificationsSupported) return;
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    ElMessage.warning("浏览器未授权桌面提醒");
    return;
  }
  await saveNotification("browser", true);
}
// 读取提醒计数，有新消息且用户授权时显示桌面提醒。
async function refreshNotifications() {
  try {
    const data = (await messagesApi.notifications()).data || {};
    if (!alive) return;
    const count = Number(data.unhandledCount) || 0;
    if (notificationCount != null && count > notificationCount && settings.value.notifications?.enabled && settings.value.notifications?.browser && browserNotificationsSupported && Notification.permission === "granted") new Notification("PostSail 新消息", { body: `新增 ${count - notificationCount} 条待处理消息` });
    notificationCount = count;
    notifications.value = data;
  } catch (error) {
    if (activeTab.value === "notifications") loadError.value = frontendError(error, "提醒加载失败");
  }
}
// 从提醒跳转到具体消息详情。
function openFromNotification(message) {
  activeTab.value = "messages";
  filters.state = "all";
  loadMessages();
  openMessage(message.id);
}
onMounted(async () => {
  await loadMetadata();
  await Promise.all([loadMessages(), refreshNotifications()]);
  notificationTimer = setInterval(refreshNotifications, 3e4);
});
onBeforeUnmount(() => {
  alive = false;
  listVersion++;
  detailVersion++;
  tabVersion++;
  clearTimeout(syncTimer);
  clearInterval(notificationTimer);
});
</script>

<style scoped>
.message-workspace { max-width: 1700px; margin: 0 auto; color: #273448; }.workspace-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-bottom: 24px; }.kicker { margin: 0 0 6px; font-size: 12px; color: #8b95a5; }h1 { font-size: 25px; letter-spacing: -.5px; margin: 0 0 8px; font-weight: 650; }.description { margin: 0; font-size: 13px; color: #788498; }.message-counters { display: flex; gap: 36px; }.message-counters button { background: none; border: 0; cursor: pointer; display: flex; flex-direction: column; gap: 6px; padding: 0; color: #8390a2; font-size: 12px; text-align: left; }.message-counters strong { color: #2e3d54; font-size: 26px; font-weight: 650; }.workspace-alert { margin: 0 0 14px; }.filter-bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; padding: 6px 0 12px; }.filter-bar :deep(.el-select) { width: 140px; }.filter-bar :deep(.el-input) { width: 240px; }.filter-bar :deep(.el-button) { margin: 0; }.sync-note { font-size: 12px; color: #8d98a9; margin: 0 0 18px; line-height: 1.6; }
.conversation-workspace { display: grid; grid-template-columns: minmax(270px, 360px) minmax(0, 1fr); border: 1px solid #e6eaf0; border-radius: 7px; min-height: 620px; overflow: hidden; }.message-rail { border-right: 1px solid #e6eaf0; background: #fafbfd; display: flex; flex-direction: column; min-width: 0; }.rail-heading { display: flex; justify-content: space-between; align-items: center; padding: 17px 20px; font-size: 12px; color: #8d97a6; border-bottom: 1px solid #edf0f4; }.message-list { flex: 1; min-height: 430px; max-height: 650px; overflow: auto; }.message-row { width: 100%; border: 0; border-bottom: 1px solid #edf0f4; background: transparent; text-align: left; padding: 18px 20px; cursor: pointer; transition: background-color 130ms ease; }.message-row:hover { background: #f0f4fb; }.message-row.selected { background: #eaf1ff; box-shadow: inset 3px 0 #3577ec; }.message-row-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }.message-row-top strong { font-size: 13px; font-weight: 550; color: #526077; }.message-row.unread .message-row-top strong { color: #20304a; font-weight: 650; }.message-row-top span { font-size: 10px; color: #99a3b2; flex-shrink: 0; }.message-row p { margin: 9px 0 11px; color: #65728a; font-size: 13px; line-height: 1.6; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; white-space: pre-wrap; }.message-row-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; color: #8e9aab; }.message-row-meta > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.unhandled-dot { width: 5px; height: 5px; background: #3577ec; border-radius: 50%; flex-shrink: 0; }.message-rail :deep(.el-pagination) { justify-content: center; padding: 14px 4px; border-top: 1px solid #e8edf2; }.conversation-panel { min-width: 0; display: flex; flex-direction: column; background: #fff; }.conversation-panel > :deep(.el-empty) { margin: auto; }.conversation-heading { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 20px 24px; border-bottom: 1px solid #edf0f4; }.conversation-heading h2 { font-size: 16px; margin: 0 0 6px; font-weight: 600; }.conversation-heading span { font-size: 12px; color: #8a95a5; }.conversation-actions { display: flex; align-items: center; flex-shrink: 0; }.item-context { margin: 0; padding: 12px 24px; font-size: 12px; color: #8a95a5; background: #fafbfd; }.conversation-content { padding: 25px; flex: 1; min-height: 250px; max-height: 500px; overflow: auto; }.incoming-message, .outgoing-message { margin-bottom: 25px; }.bubble-label { color: #8a96a8; font-size: 11px; display: flex; align-items: center; gap: 8px; }.incoming-message p, .outgoing-message p { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; line-height: 1.8; margin: 8px 0; color: #394960; padding: 12px 16px; max-width: 90%; border-radius: 5px; background: #f4f6f9; }.outgoing-message { display: flex; flex-direction: column; align-items: flex-end; }.outgoing-message p { background: #edf3ff; }.account-capability-note { display: block; margin-top: 5px; line-height: 1.6; }.reply-error, .account-error { font-size: 11px; color: #c27758; }.resolve-actions { font-size: 11px; color: #b28753; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }.resolve-actions :deep(.el-button) { margin-left: 0; }.reply-composer { padding: 18px 24px 20px; border-top: 1px solid #edf0f4; }.reply-composer :deep(.el-alert) { margin-bottom: 14px; }.composer-toolbar { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin: 0 0 12px; flex-wrap: wrap; }.composer-toolbar :deep(.el-select) { width: 210px; }.composer-footer { display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-top: 13px; }.composer-footer span { font-size: 11px; color: #98a1b0; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 12px 0 24px; }.section-heading h2 { margin: 0 0 8px; font-size: 17px; font-weight: 600; }.section-heading p, .collection-settings p, .notification-settings p { color: #8b96a7; font-size: 12px; line-height: 1.7; margin: 0; }.muted { color: #8d98a9; font-size: 12px; line-height: 1.7; }.capability-list { border-top: 1px solid #e9edf2; margin-bottom: 25px; }.capability-row { display: grid; grid-template-columns: 120px 150px 95px 1fr; align-items: center; gap: 16px; padding: 17px 0; border-bottom: 1px solid #e9edf2; font-size: 13px; }.capability-row strong { font-weight: 600; }.capability-row > span { color: #7d899b; }.capability-row :deep(.el-tag) { justify-self: start; }.capability-row p { color: #8c97a6; font-size: 12px; margin: 0; line-height: 1.6; }.account-error { display: block; margin-top: 5px; }.collection-settings { border-top: 1px solid #e9edf2; margin-top: 30px; padding-top: 25px; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 16px; }.collection-settings h3 { margin: 0 0 8px; font-size: 15px; font-weight: 600; }.settings-form { width: 100%; margin-top: 10px; }.settings-form :deep(.el-select) { width: 245px; }.settings-form :deep(.el-form-item) { margin-bottom: 12px; }.notification-settings { display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 22px 0; border-bottom: 1px solid #e9edf2; }.notification-settings strong { font-size: 14px; font-weight: 550; }.notification-settings p { margin-top: 7px; }.notification-feed { margin-top: 25px; }.notification-feed > button { width: 100%; display: block; text-align: left; background: transparent; padding: 18px 0; border: 0; border-bottom: 1px solid #e9edf2; cursor: pointer; }.notification-feed > button:hover { background: #fafbfd; }.notification-feed strong { font-weight: 550; font-size: 13px; margin-right: 12px; color: #39465b; }.notification-feed span, .notification-feed small { font-size: 11px; color: #8d98a9; }.notification-feed p { color: #68758a; margin: 8px 0; line-height: 1.7; }.local-resolution { display: flex; flex-direction: column; align-items: flex-start; margin: 20px 0; }.form-row { display: flex; gap: 20px; }.form-row > :deep(.el-form-item) { width: 50%; }.form-row :deep(.el-select), :deep(.el-form .el-select) { width: 100%; }
@media (max-width: 1100px) { .conversation-workspace { grid-template-columns: 290px minmax(0, 1fr); }.conversation-heading { flex-direction: column; align-items: flex-start; }.filter-bar :deep(.el-select) { width: 135px; } }
@media (max-width: 750px) { .workspace-header { align-items: flex-start; flex-direction: column; gap: 20px; }.message-counters { gap: 45px; }.filter-bar :deep(.el-input) { width: 100%; }.filter-bar :deep(.el-select) { width: calc(50% - 5px); }.conversation-workspace { grid-template-columns: 1fr; }.message-rail { border-right: 0; border-bottom: 1px solid #e6eaf0; }.message-list { max-height: 290px; min-height: 120px; }.conversation-panel { min-height: 400px; }.conversation-heading, .reply-composer { padding: 18px; }.conversation-content { padding: 18px; }.composer-footer { align-items: flex-start; }.composer-footer span { line-height: 1.7; }.capability-row { grid-template-columns: 90px 1fr 85px; gap: 10px; }.capability-row p { grid-column: 1 / -1; }.section-heading { align-items: flex-start; }.form-row { flex-direction: column; gap: 0; }.form-row > :deep(.el-form-item) { width: 100%; } }
</style>
