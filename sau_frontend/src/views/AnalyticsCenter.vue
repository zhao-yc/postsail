<template>
  <div class="analytics-workspace">
    <header class="workspace-header">
      <div><p class="kicker">运营 / 数据分析</p><h1>数据中心</h1><p class="description">账号、作品与负责人数据；增长指标以连续采集快照为依据。</p></div>
      <div class="header-actions"><router-link to="/content-stats"><el-button>作品同步详情</el-button></router-link><el-button :loading="refreshing" @click="refreshAll">刷新数据</el-button><el-button @click="openPush">数据推送</el-button></div>
    </header>

    <div class="filter-bar">
      <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" :shortcuts="dateShortcuts" @change="filterChanged" />
      <el-select v-model="filters.platform" placeholder="全部平台" clearable @change="platformChanged"><el-option v-for="item in platformOptions" :key="item.platform" :label="item.platformLabel || item.label || platformLabel(item.platform)" :value="item.platform" /></el-select>
      <el-select v-model="filters.accountId" placeholder="全部账号" filterable clearable @change="filterChanged"><el-option v-for="item in accountOptions" :key="item.accountId" :label="`${item.accountName} · ${platformLabel(item.platform)}`" :value="item.accountId" /></el-select>
      <el-select v-model="filters.owner" placeholder="全部负责人" filterable allow-create clearable @change="filterChanged"><el-option label="未分配负责人" value="__unassigned__" /><el-option v-for="owner in ownerOptions" :key="owner" :label="owner" :value="owner" /></el-select>
      <el-select v-model="filters.tag" placeholder="全部分组" filterable clearable @change="filterChanged"><el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" /></el-select>
      <el-select v-if="activeTab === 'accounts'" v-model="filters.status" placeholder="全部状态" clearable @change="filterChanged"><el-option label="正常" :value="1" /><el-option label="登录失效" :value="0" /></el-select>
    </div>
    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" class="workspace-alert" />
    <el-alert v-if="coverage?.boundaryMessage" :title="coverage.boundaryMessage" type="warning" :closable="false" show-icon class="workspace-alert" /><el-alert v-if="coverage?.message" :title="coverage.message" type="info" :closable="false" show-icon class="workspace-alert" />

    <el-tabs v-model="activeTab" @tab-change="tabChanged">
      <el-tab-pane label="仪表盘" name="overview" /><el-tab-pane label="账号数据" name="accounts" /><el-tab-pane label="作品数据" name="works" /><el-tab-pane label="排行榜" name="rankings" /><el-tab-pane label="负责人数据" name="owners" />
    </el-tabs>

    <section v-if="activeTab === 'overview'" v-loading="loading" class="overview">
      <div class="metric-strip"><div v-for="metric in overviewMetrics" :key="metric.key" class="metric-cell"><span>{{ metric.label }}</span><strong>{{ number(overview.summary?.[metric.key]) }}</strong><small v-if="overview.comparison?.[metric.key]" :class="changeClass(overview.comparison[metric.key].change)">{{ comparisonText(overview.comparison[metric.key]) }}</small><small v-else>{{ metric.hint || '当前筛选范围' }}</small></div></div>
      <div class="section-heading"><h2>数据趋势</h2><el-radio-group v-model="trendMetric" size="small"><el-radio-button v-for="metric in trendMetrics" :key="metric.key" :value="metric.key">{{ metric.label }}</el-radio-button></el-radio-group></div>
      <TrendChart :points="overview.trends || []" :metric="trendMetric" :label="metricLabel(trendMetric)" />
      <div class="section-heading"><h2>平台概览</h2><span class="muted">最近同步 {{ time(coverage?.lastSyncedAt) }}</span></div>
      <el-table :data="overview.platforms || []" empty-text="暂无平台数据，先到作品同步详情采集数据"><el-table-column label="平台" min-width="130"><template #default="{ row }">{{ row.platformLabel || platformLabel(row.platform) }}</template></el-table-column><el-table-column v-for="metric in platformMetrics" :key="metric.key" :label="metric.label" min-width="110"><template #default="{ row }">{{ number(row[metric.key]) }}</template></el-table-column></el-table>
      <p class="scope-note">作品发布数按发布时间统计；播放、点赞等增长按已有真实基线的快照差值统计，按后一次采样日期归属，可能覆盖查询起点前时间。首次采集仅建立基线，不代表自然日精确新增互动。</p>
    </section>

    <section v-else class="detail-section" v-loading="loading">
      <div class="table-toolbar">
        <div class="table-options">
          <template v-if="activeTab === 'rankings'"><el-radio-group v-model="rankEntity" @change="filterChanged"><el-radio-button value="accounts">账号榜</el-radio-button><el-radio-button value="works">作品榜</el-radio-button><el-radio-button value="owners">负责人榜</el-radio-button></el-radio-group><el-select v-model="rankMetric" @change="filterChanged"><el-option v-for="metric in rankMetrics" :key="metric.key" :label="metric.label" :value="metric.key" /></el-select></template>
          <el-input v-model="filters.keyword" clearable :placeholder="entity === 'works' ? '搜索作品标题或账号' : '搜索账号或负责人'" @clear="filterChanged" @keyup.enter="filterChanged"><template #append><el-button @click="filterChanged">搜索</el-button></template></el-input>
          <el-select v-if="entity !== 'owners'" v-model="displayMode" style="width: 120px" @change="modeChanged"><el-option label="累计数据" value="total" /><el-option label="增量数据" value="growth" /></el-select>
        </div>
        <div class="table-actions"><el-popover placement="bottom-end" :width="280" trigger="click"><template #reference><el-button>表头字段</el-button></template><div class="column-picker"><el-checkbox-group v-model="visibleMetricKeys" @change="saveColumns"><el-checkbox v-for="metric in allMetrics" :key="metric.key" :value="metric.key" :label="metric.label" /></el-checkbox-group></div></el-popover><el-button :loading="exporting" @click="exportData">导出 CSV</el-button></div>
      </div>
      <p v-if="activeTab === 'rankings'" class="scope-note">{{ entity === 'works' ? '作品排行按累计指标排序。' : '账号与负责人流量排行按区间增长排序，粉丝总数排行按最近实采粉丝排序；缺失数据不参与名次。' }}</p><p class="scope-note" v-if="entity !== 'owners'">{{ displayMode === 'growth' ? '增量为已有真实基线的观测差值，按后一次采样日期归属；可能覆盖查询起点前时间，不代表自然日精确流量。缺少基线显示 —。' : entity === 'accounts' ? '账号累计值为截止结束日期已观测作品的最新值；开始日期控制增量与发布数。' : '作品累计值为最近一次采集指标；日期筛选按作品发布时间。' }}</p>
      <el-table :data="rows" :empty-text="loadError ? '数据加载失败，请刷新重试' : '当前筛选条件下暂无数据'" @sort-change="sortChanged" row-key="_key">
        <el-table-column v-if="activeTab === 'rankings'" prop="rank" label="排名" width="70" />
        <template v-if="entity === 'works'"><el-table-column label="作品" min-width="280"><template #default="{ row }"><div class="work-cell"><img v-if="safeImage(row.coverUrl)" :src="row.coverUrl" alt="作品封面" loading="lazy" referrerpolicy="no-referrer" /><div><strong>{{ row.title || '无标题作品' }}</strong><small>{{ row.accountName }} · {{ row.platformLabel || platformLabel(row.platform) }}</small></div></div></template></el-table-column><el-table-column prop="publishedAt" label="发布时间" min-width="150"><template #default="{ row }">{{ time(row.publishedAt) }}</template></el-table-column></template>
        <template v-else-if="entity === 'accounts'"><el-table-column label="账号" min-width="210"><template #default="{ row }"><div class="identity-cell"><strong>{{ row.accountName }}</strong><small>{{ row.platformLabel || platformLabel(row.platform) }}</small></div></template></el-table-column><el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="row.status === 0 || row.status === 'invalid' ? 'warning' : 'success'" size="small">{{ accountStatus(row.status) }}</el-tag><small v-if="row.statsSupported === false" class="unsupported-note">暂不支持采集</small></template></el-table-column></template>
        <el-table-column label="负责人" min-width="120"><template #default="{ row }">{{ row.owner || '未分配' }}</template></el-table-column>
        <el-table-column v-if="entity === 'owners'" label="账号数" min-width="95"><template #default="{ row }">{{ number(row.accountCount) }}</template></el-table-column>
        <el-table-column v-if="entity !== 'works'" label="作品数" min-width="95"><template #default="{ row }">{{ number(row.workCount) }}</template></el-table-column>
        <el-table-column v-if="activeTab === 'rankings'" :label="metricLabel(rankMetric) + '排名值'" min-width="130"><template #default="{ row }"><strong>{{ number(row.metricValue) }}</strong></template></el-table-column>
        <el-table-column v-for="metric in visibleMetrics" :key="metric.key" :prop="metric.key" :label="metric.label" :sortable="activeTab === 'rankings' ? false : 'custom'" min-width="112"><template #default="{ row }">{{ number(metricValue(row, metric.key)) }}</template></el-table-column>
        <el-table-column v-if="entity !== 'owners'" label="最近同步" min-width="150"><template #default="{ row }">{{ time(row.lastSyncedAt) }}</template></el-table-column>
        <el-table-column v-if="entity === 'accounts'" label="操作" width="155" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="!!syncingAccount || row.statsSupported === false" :loading="syncingAccount === row.accountId" @click="syncAccount(row)">同步</el-button><el-button link @click="editAccount(row)">设置</el-button></template></el-table-column>
      </el-table>
      <p v-if="entity === 'owners'" class="scope-note">负责人数据按当前账号归属聚合；历史作品发布人信息尚未采集。</p><div class="pagination"><span class="muted">共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @size-change="filterChanged" @current-change="loadData" /></div>
    </section>

    <el-dialog v-model="accountDialog" title="账号负责人和分组" width="min(480px, calc(100vw - 32px))"><el-form label-position="top"><el-form-item label="账号"><el-input :model-value="accountForm.accountName" disabled /></el-form-item><el-form-item label="负责人"><el-input v-model="accountForm.owner" maxlength="80" placeholder="可留空" /></el-form-item><el-form-item label="分组标签"><el-select v-model="accountForm.tags" multiple filterable allow-create default-first-option placeholder="输入分组标签后回车"><el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" /></el-select></el-form-item></el-form><template #footer><el-button :disabled="savingSettings" @click="accountDialog = false">取消</el-button><el-button type="primary" :loading="savingSettings" @click="saveAccount">保存</el-button></template></el-dialog>
    <el-dialog v-model="pushDialog" title="报表推送" width="min(700px, calc(100vw - 32px))" :close-on-click-modal="!pushingReport && !savingPush" @closed="webhookInput = ''; secretInput = ''">
      <div v-loading="loadingPush">
        <el-alert v-if="pushError" :title="pushError" type="error" :closable="false" class="workspace-alert" />
        <el-form label-position="top" class="report-form">
          <div class="form-grid"><el-form-item label="推送渠道"><el-select v-model="pushForm.channel"><el-option label="钉钉群机器人" value="dingtalk" /><el-option label="飞书群机器人" value="feishu" /><el-option label="企业微信群机器人" value="wecom" /></el-select></el-form-item><el-form-item label="自动报表"><el-switch v-model="pushForm.enabled" active-text="保存后按计划发送" inactive-text="已关闭" /></el-form-item></div>
          <el-form-item label="机器人 Webhook 地址"><el-input v-model="webhookInput" type="password" show-password autocomplete="off" :placeholder="pushSettings.hasWebhook ? '已配置，留空保留原地址' : '粘贴所选渠道的 HTTPS 机器人地址'" /><small class="muted" v-if="pushSettings.hasWebhook">已保存地址：{{ pushSettings.webhookMasked }}。地址包含密钥，只展示脱敏结果。</small></el-form-item>
          <el-form-item v-if="pushForm.channel !== 'wecom'" label="机器人签名密钥（可选）"><el-input v-model="secretInput" type="password" show-password autocomplete="off" :placeholder="pushSettings.hasSecret ? '已保存，留空保留原密钥' : '未配置签名校验时可留空'" /><el-checkbox v-if="pushSettings.hasSecret" v-model="clearSecret">清除已保存的签名密钥</el-checkbox></el-form-item><el-form-item label="推送账号"><el-select v-model="pushForm.accountIds" multiple filterable placeholder="选择参与报表的账号"><el-option v-for="account in allAccounts" :key="account.accountId" :label="`${account.accountName} · ${platformLabel(account.platform)}`" :value="account.accountId" /></el-select></el-form-item>
          <div class="form-grid"><el-form-item label="报表周期"><el-checkbox-group v-model="pushForm.frequencies"><el-checkbox value="daily" label="日报" /><el-checkbox value="weekly" label="周报" /><el-checkbox value="monthly" label="月报" /></el-checkbox-group></el-form-item><el-form-item label="发送时间"><el-time-picker v-model="pushForm.sendTime" value-format="HH:mm" format="HH:mm" placeholder="选择发送时间" :clearable="false" /></el-form-item></div>
          <el-form-item label="发送时区"><el-select v-model="pushForm.utcOffsetMinutes"><el-option v-for="zone in timeZones" :key="zone.value" :label="zone.label" :value="zone.value" /></el-select><small class="muted">日报发送前一日，周报发送前 7 日，月报发送上一个自然月的报表。</small></el-form-item>
        </el-form>
        <div class="push-save-row"><span class="muted">保存设置只更新配置；自动报表关闭时不会外发。</span><el-button :loading="savingPush" :disabled="loadingPush" @click="savePushConfiguration">保存设置</el-button></div>
        <div class="manual-report"><div class="section-heading"><div><h2>手动发送报表</h2><p>将发送到已保存的{{ channelLabel(pushSettings.channel) }}，日报按前一日、周报按前 7 日、月报按上一个自然月汇总。</p></div><el-button text @click="openLegacyPush">旧版作品推送</el-button></div><div class="manual-report-actions"><el-radio-group v-model="manualPeriod"><el-radio-button value="daily">日报</el-radio-button><el-radio-button value="weekly">周报</el-radio-button><el-radio-button value="monthly">月报</el-radio-button></el-radio-group><el-button type="primary" :loading="pushingReport" :disabled="!pushSettings.hasWebhook || !pushSettings.accountIds?.length || manualPushUncertain" @click="sendReport">发送报表</el-button></div><el-alert v-if="manualPushUncertain" title="上次发送结果待确认，请先到目标群核查，不能直接重复发送。" type="warning" :closable="false" class="workspace-alert" /></div>
        <div class="push-history"><div class="section-heading"><h3>发送记录</h3><el-button text :loading="loadingPushRecords" @click="refreshPushRecords">刷新记录</el-button></div><el-table :data="pushRecords" empty-text="尚无报表发送记录" size="small"><el-table-column label="周期" width="95"><template #default="{ row }">{{ periodLabel(row.period) }}</template></el-table-column><el-table-column label="发送状态" width="125"><template #default="{ row }"><el-tag :type="row.status === 'sent' ? 'success' : row.status === 'unknown' ? 'warning' : 'danger'" size="small">{{ pushStatusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column label="时间" min-width="145"><template #default="{ row }">{{ time(row.createdAt) }}</template></el-table-column><el-table-column prop="error" label="说明" min-width="160" show-overflow-tooltip /><el-table-column label="核查" width="150"><template #default="{ row }"><template v-if="row.status === 'unknown'"><el-button link size="small" :loading="resolvingPush === row.id" @click="resolvePushRecord(row, 'sent')">确认已发送</el-button><el-button link size="small" :loading="resolvingPush === row.id" @click="resolvePushRecord(row, 'not_sent')">确认未发送</el-button></template></template></el-table-column></el-table><p class="muted">最近自动运行 {{ time(pushSettings.lastRunAt) }}<span v-if="pushSettings.error"> · {{ pushSettings.error }}</span></p></div>
      </div><template #footer><el-button :disabled="pushingReport || savingPush" @click="pushDialog = false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="legacyPushDialog" title="作品数据推送到钉钉" width="min(540px, calc(100vw - 32px))" :close-on-click-modal="!pushing"><p class="dialog-note">选择已同步账号，将最近作品的实际采集数据发送到已配置的钉钉群机器人。</p><el-alert type="info" :closable="false" title="旧版作品明细仅支持手动推送；定时报表请使用报表推送设置。" /><el-checkbox-group v-model="pushIds" class="push-list" :disabled="pushing"><el-checkbox v-for="account in pushAccounts" :key="account.accountId" :value="account.accountId" :label="`${account.accountName} · ${platformLabel(account.platform)}`" /></el-checkbox-group><el-empty v-if="!pushAccounts.length" description="暂无可推送账号，请先同步作品数据" :image-size="60" /><el-alert v-if="pushResult" :title="pushResult" type="info" :closable="false" /><template #footer><el-button :disabled="pushing" @click="legacyPushDialog = false">关闭</el-button><el-button type="primary" :loading="pushing" :disabled="!pushIds.length" @click="pushData">发送数据</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { analyticsApi } from "@/api/analytics";
import { statsApi } from "@/api/stats";
import TrendChart from "@/components/analytics/TrendChart.vue";
// 使用本地日历日期，避免 UTC 转换造成筛选日期偏移一天。
function dayString(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
// 生成含今日的最近若干天区间。
function recentDays(days) {
  const end = /* @__PURE__ */ new Date();
  const start = /* @__PURE__ */ new Date();
  start.setDate(start.getDate() - days + 1);
  return [dayString(start), dayString(end)];
}
const dateRange = ref(recentDays(30));
const dateShortcuts = [7, 30, 90].map((days) => ({ text: `近 ${days} 日`, value: () => {
  const end = /* @__PURE__ */ new Date();
  const start = /* @__PURE__ */ new Date();
  start.setDate(start.getDate() - days + 1);
  return [start, end];
} }));
const filters = reactive({ platform: "", accountId: "", owner: "", tag: "", keyword: "", status: "" });
const activeTab = ref("overview"), rankEntity = ref("accounts"), rankMetric = ref("playCount"), displayMode = ref("total"), trendMetric = ref("playCount");
const overview = ref({}), rows = ref([]), total = ref(0), page = ref(1), pageSize = ref(20), sortBy = ref(""), sortOrder = ref("desc");
const loading = ref(false), refreshing = ref(false), loadError = ref(""), capabilities = ref([]), settings = ref([]), allAccounts = ref([]), tableCoverage = ref(null);
const syncingAccount = ref(null), accountDialog = ref(false), savingSettings = ref(false), accountForm = reactive({ accountId: null, accountName: "", owner: "", tags: [] });
const pushDialog = ref(false), legacyPushDialog = ref(false), pushIds = ref([]), pushing = ref(false), pushResult = ref(""), exporting = ref(false);
const pushSettings = ref({ enabled: false, channel: "dingtalk", accountIds: [] }), pushRecords = ref([]), loadingPush = ref(false), pushError = ref(""), savingPush = ref(false), pushingReport = ref(false), webhookInput = ref(""), manualPeriod = ref("daily"), manualPushKey = ref(""), localPushUncertain = ref(false), secretInput = ref(""), clearSecret = ref(false), resolvingPush = ref(null), loadingPushRecords = ref(false), manualReportId = ref(null), manualAttempt = ref(null);
const pushForm = reactive({ enabled: false, channel: "dingtalk", accountIds: [], frequencies: ["daily"], sendTime: "09:00", utcOffsetMinutes: 480 });
const timeZones = Array.from({ length: 27 }, (_, index) => {
  const hours = index - 12;
  return { value: hours * 60, label: `UTC${hours >= 0 ? "+" : ""}${hours}:00${hours === 8 ? "（北京时间）" : ""}` };
});
const manualPushUncertain = computed(() => localPushUncertain.value || pushRecords.value.some((record) => ["unknown", "sending"].includes(record.status)));
let loadVersion = 0, metaVersion = 0, alive = true;
const labels = { douyin: "抖音", kuaishou: "快手", xiaohongshu: "小红书", bilibili: "B站", tencent: "视频号", channels: "视频号", baijiahao: "百家号", toutiao: "今日头条", sohu: "搜狐", zhihu: "知乎" };
const allMetrics = [{ key: "publishedCount", label: "发布数" }, { key: "followerCount", label: "总粉丝" }, { key: "newFollowers", label: "新增关注" }, { key: "playCount", label: "播放" }, { key: "likeCount", label: "点赞" }, { key: "commentCount", label: "评论" }, { key: "collectCount", label: "收藏" }, { key: "shareCount", label: "分享" }];
const trendMetrics = allMetrics.filter((item) => item.key !== "followerCount");
const rankMetrics = computed(() => allMetrics.filter((item) => item.key !== "shareCount" && !(rankEntity.value === "works" && ["followerCount", "newFollowers", "publishedCount"].includes(item.key))));
const overviewMetrics = [{ key: "accountCount", label: "账号数" }, { key: "publishedCount", label: "发布作品" }, { key: "newFollowers", label: "新增关注", hint: "平台未提供时显示 —" }, ...allMetrics.filter((item) => ["playCount", "likeCount", "commentCount"].includes(item.key))];
const platformMetrics = [{ key: "accountCount", label: "账号数" }, { key: "publishedCount", label: "发布作品" }, ...allMetrics.filter((item) => ["playCount", "likeCount", "commentCount"].includes(item.key))];
const visibleMetricKeys = ref(readColumns());
const visibleMetrics = computed(() => allMetrics.filter((metric) => visibleMetricKeys.value.includes(metric.key) && !(entity.value === "works" && ["followerCount", "newFollowers", "publishedCount"].includes(metric.key))));
const entity = computed(() => activeTab.value === "rankings" ? rankEntity.value : activeTab.value);
const coverage = computed(() => activeTab.value === "overview" ? overview.value.coverage : tableCoverage.value);
const platformOptions = computed(() => {
  const map = new Map(capabilities.value.map((item) => [item.platform, item]));
  allAccounts.value.forEach((item) => {
    if (!map.has(item.platform)) map.set(item.platform, { platform: item.platform });
  });
  return [...map.values()];
});
const accountOptions = computed(() => allAccounts.value.filter((item) => !filters.platform || item.platform === filters.platform));
const ownerOptions = computed(() => [...new Set(settings.value.map((item) => item.owner).filter(Boolean))]);
const tagOptions = computed(() => [...new Set(settings.value.flatMap((item) => item.tags || []))]);
const pushAccounts = computed(() => allAccounts.value.filter((item) => item.statsSupported !== false && ["douyin", "kuaishou", "xiaohongshu", "bilibili"].includes(item.platform) && item.lastSyncedAt));
// 显示平台的中文名称。
function platformLabel(value) {
  return labels[value] || value || "未知平台";
}
// 读取指标的中文名称。
function metricLabel(value) {
  return allMetrics.find((item) => item.key === value)?.label || value;
}
// 缺失指标显示横线，已知指标按中文数字格式显示。
function number(value) {
  return value == null || !Number.isFinite(Number(value)) ? "—" : new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}
// 优先显示后端中文错误；传输层英文摘要替换为操作相关的中文提示。
function frontendError(error, fallback) {
  const message = error.response?.data?.msg || error.response?.data?.message || error.message;
  return typeof message === "string" && /[\u4e00-\u9fff]/.test(message) ? message : fallback;
}
// 显示服务端返回的时间，缺少时间时给出明确状态。
function time(value) {
  if (!value) return "尚未同步";
  const text = String(value);
  if (/(?:Z|[+-]\d{2}:\d{2})$/.test(text)) {
    const parsed = new Date(text);
    if (!Number.isNaN(parsed.getTime())) return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(parsed);
  }
  return text.replace("T", " ").slice(0, 19);
}
// 仅允许公开 HTTP 或 HTTPS 封面地址。
function safeImage(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}
// 保留真实账号登录状态的中文含义。
function accountStatus(value) {
  return { 0: "登录失效", 1: "正常", unsupported: "暂不支持采集", invalid: "登录失效", supported: "可采集", valid: "可采集", active: "可采集" }[value] || value || "未校验";
}
// 显示与上一等长周期的已知差值，缺少基线不伪造环比。
function comparisonText(value) {
  if (value.change == null) return "暂无可比基线";
  const prefix = value.change > 0 ? "+" : "";
  return `较上期 ${prefix}${number(value.change)}${value.changePercent == null ? "" : `（${prefix}${number(value.changePercent)}%）`}`;
}
// 按增长方向应用文字提示颜色。
function changeClass(value) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}
// 按累计或增量模式读取指标，缺失增量保持为空。
function metricValue(row, key) {
  return displayMode.value === "growth" && entity.value !== "owners" && !["publishedCount", "followerCount", "newFollowers"].includes(key) ? row.growth?.[key] : row[key];
}
// 读取当前浏览器的指标列偏好并校验白名单。
function readColumns() {
  try {
    const stored = JSON.parse(localStorage.getItem("omnipost.analytics.columns"));
    return Array.isArray(stored) ? stored.filter((key) => allMetrics.some((item) => item.key === key)) : ["publishedCount", "playCount", "likeCount", "commentCount", "collectCount", "shareCount"];
  } catch {
    return ["publishedCount", "playCount", "likeCount", "commentCount", "collectCount", "shareCount"];
  }
}
// 仅在当前浏览器保存表头偏好。
function saveColumns() {
  localStorage.setItem("omnipost.analytics.columns", JSON.stringify(visibleMetricKeys.value));
}
// 统一构造当前日期、账号、负责人和分页筛选。
function params() {
  return { ...filters, startDate: dateRange.value?.[0], endDate: dateRange.value?.[1], page: page.value, pageSize: pageSize.value, sortBy: sortBy.value || void 0, sortOrder: sortOrder.value };
}
// 请求序号确保旧筛选请求不会覆盖用户当前选择，切换页签时立即清空旧数据。
async function loadData() {
  const version = ++loadVersion;
  loading.value = true;
  loadError.value = "";
  rows.value = [];
  total.value = 0;
  tableCoverage.value = null;
  if (activeTab.value === "overview") overview.value = {};
  try {
    const data = (await analyticsApi[activeTab.value](activeTab.value === "rankings" ? { ...params(), entity: rankEntity.value, metric: rankMetric.value } : params())).data || {};
    if (!alive || version !== loadVersion) return;
    if (activeTab.value === "overview") overview.value = data;
    else {
      rows.value = (data.items || []).map((row, index) => ({ ...row, _key: `${row.platform || ""}:${row.accountId || row.owner || ""}:${row.itemId || index}` }));
      total.value = data.total || 0;
      tableCoverage.value = data.coverage;
    }
  } catch (error) {
    if (alive && version === loadVersion) loadError.value = frontendError(error, "数据加载失败，请稍后刷新");
  } finally {
    if (alive && version === loadVersion) loading.value = false;
  }
}
// 并行载入平台能力、账号归属和筛选候选。
async function loadMetadata() {
  const version = ++metaVersion;
  const results = await Promise.allSettled([analyticsApi.capabilities(), analyticsApi.accountSettings(), loadAllAccounts()]);
  if (!alive || version !== metaVersion) return;
  if (results[0].status === "fulfilled") {
    const value = results[0].value.data;
    capabilities.value = Array.isArray(value) ? value : value?.platforms || value?.items || [];
  }
  if (results[1].status === "fulfilled") settings.value = results[1].value.data?.items || [];
  if (results[2].status === "fulfilled") allAccounts.value = results[2].value;
  if (results.some((result) => result.status === "rejected")) loadError.value = "部分筛选选项加载失败，请刷新数据重试";
}
// 后端分页上限为 200；逐页读取筛选候选，避免账号数量较多时漏掉后面的账号。
async function loadAllAccounts() {
  const items = [];
  let nextPage = 1, expectedTotal = Infinity;
  while (alive && items.length < expectedTotal) {
    const data = (await analyticsApi.accounts({ page: nextPage++, pageSize: 200 })).data || {};
    const batch = data.items || [];
    items.push(...batch);
    expectedTotal = Number(data.total) || 0;
    if (!batch.length) break;
  }
  return items;
}
// 筛选改变时回到第一页并重新读取数据。
function filterChanged() {
  if (activeTab.value === "rankings" && rankEntity.value === "works" && ["followerCount", "newFollowers", "publishedCount"].includes(rankMetric.value)) rankMetric.value = "playCount";
  page.value = 1;
  loadData();
}
// 切换平台时清除原平台的账号筛选。
function platformChanged() {
  filters.accountId = "";
  filterChanged();
}
// 切换数据维度时重置搜索、状态和排序。
function tabChanged() {
  filters.status = "";
  filters.keyword = "";
  sortBy.value = "";
  filterChanged();
}
// 将表格排序转换为后端白名单排序参数。
function modeChanged() {
  sortBy.value = "";
  filterChanged();
}
// 增量展示按增量排序，避免累计值排序与用户看到的指标不一致。
function sortChanged({ prop, order }) {
  sortBy.value = order ? displayMode.value === "growth" && entity.value !== "owners" && !["publishedCount", "followerCount", "newFollowers"].includes(prop) ? `growth.${prop}` : prop : "";
  sortOrder.value = order === "ascending" ? "asc" : "desc";
  filterChanged();
}
// 重新读取筛选项和当前维度数据。
async function refreshAll() {
  refreshing.value = true;
  try {
    await Promise.all([loadMetadata(), loadData()]);
  } finally {
    refreshing.value = false;
  }
}
// 显式同步单个账号并提示真实采集限制。
async function syncAccount(row) {
  if (syncingAccount.value) return;
  syncingAccount.value = row.accountId;
  try {
    const response = await analyticsApi.refreshAccount(row.accountId);
    ElMessage.success("账号数据已同步");
    if (response.data?.warnings?.length) ElMessage.warning(response.data.warnings.join("；"));
    await refreshAll();
  } catch (error) {
    loadError.value = frontendError(error, "同步失败，请检查账号登录状态");
  } finally {
    syncingAccount.value = null;
  }
}
// 复制账号归属设置，避免表单直接污染表格。
function editAccount(row) {
  Object.assign(accountForm, { accountId: row.accountId, accountName: row.accountName, owner: row.owner || "", tags: [...row.tags || []] });
  accountDialog.value = true;
}
// 保存负责人和分组标签后刷新聚合结果。
async function saveAccount() {
  if (savingSettings.value) return;
  savingSettings.value = true;
  try {
    await analyticsApi.saveAccountSettings({ accountId: accountForm.accountId, owner: accountForm.owner.trim(), tags: accountForm.tags });
    accountDialog.value = false;
    ElMessage.success("账号设置已保存");
    await refreshAll();
  } finally {
    savingSettings.value = false;
  }
}
// 配置读取和保存不会调用外部发送；只在显式操作时提交报表发送请求。
async function openPush() {
  pushDialog.value = true;
  webhookInput.value = "";
  secretInput.value = "";
  clearSecret.value = false;
  pushError.value = "";
  loadingPush.value = true;
  try {
    const results = await Promise.all([analyticsApi.pushSettings(), analyticsApi.pushRecords()]);
    applyPushSettings(results[0].data || {});
    pushRecords.value = results[1].data?.items || [];
  } catch (error) {
    pushError.value = frontendError(error, "推送设置加载失败");
  } finally {
    loadingPush.value = false;
  }
}
// 将已保存推送配置复制到编辑表单，不回显机器人密钥。
function applyPushSettings(data) {
  pushSettings.value = data;
  Object.assign(pushForm, { enabled: !!data.enabled, channel: data.channel || "dingtalk", accountIds: [...data.accountIds || []], frequencies: [...data.frequencies || ["daily"]], sendTime: data.sendTime || "09:00", utcOffsetMinutes: data.utcOffsetMinutes ?? 480 });
}
// 显示已保存的机器人渠道名称。
function channelLabel(value) {
  return { dingtalk: "钉钉群机器人", feishu: "飞书群机器人", wecom: "企业微信群机器人" }[value] || "机器人";
}
// 显示日报、周报或月报名称。
function periodLabel(value) {
  return { daily: "日报", weekly: "周报", monthly: "月报" }[value] || value || "—";
}
// 区分已发送、失败与结果待核查。
function pushStatusLabel(value) {
  return { sent: "已发送", failed: "发送失败", unknown: "待核查", sending: "发送中" }[value] || value;
}
// 保存报表配置；只有显式启用开关才请求启用定时发送。
async function savePushConfiguration() {
  if (savingPush.value) return;
  if (pushForm.enabled && (!pushForm.accountIds.length || !pushForm.frequencies.length)) {
    ElMessage.warning("启用自动报表需选择账号和报表周期");
    return;
  }
  savingPush.value = true;
  pushError.value = "";
  try {
    const payload = { ...pushForm };
    if (webhookInput.value.trim()) payload.webhookUrl = webhookInput.value.trim();
    if (clearSecret.value) payload.secret = "";
    else if (secretInput.value.trim()) payload.secret = secretInput.value.trim();
    applyPushSettings((await analyticsApi.savePushSettings(payload)).data || {});
    webhookInput.value = "";
    secretInput.value = "";
    clearSecret.value = false;
    ElMessage.success("报表推送设置已保存");
  } catch (error) {
    pushError.value = frontendError(error, "推送设置保存失败");
  } finally {
    savingPush.value = false;
  }
}
// 生成与单次用户操作绑定的报表幂等键。
function newIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() || "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16);
    return (char === "x" ? value : value & 3 | 8).toString(16);
  });
}
// 超时保留原幂等键并锁定发送；不将无法确认的平台结果解释为可以重试。
async function sendReport() {
  if (pushingReport.value || manualPushUncertain.value || !pushSettings.value.hasWebhook) return;
  pushingReport.value = true;
  pushError.value = "";
  manualPushKey.value ||= newIdempotencyKey();
  manualAttempt.value = { at: Date.now(), period: manualPeriod.value, channel: pushSettings.value.channel };
  try {
    const report = (await analyticsApi.pushReport({ idempotencyKey: manualPushKey.value, period: manualPeriod.value, accountIds: pushSettings.value.accountIds })).data;
    manualReportId.value = report?.id || null;
    if (report?.status === "sent") {
      ElMessage.success("报表已发送");
      manualPushKey.value = "";
    } else if (report?.status === "failed") {
      pushError.value = report.error || "报表发送失败";
      manualPushKey.value = "";
    } else {
      localPushUncertain.value = true;
      pushError.value = report?.error || "报表发送结果待确认，请核对目标群";
    }
    await refreshPushRecords();
  } catch (error) {
    const rejectedBeforeSending = [400, 401, 403, 404, 422].includes(error.response?.status);
    localPushUncertain.value = !rejectedBeforeSending;
    if (rejectedBeforeSending) manualPushKey.value = "";
    pushError.value = frontendError(error, "报表发送结果未确认，请到目标群核查");
  } finally {
    pushingReport.value = false;
  }
}
// 发送记录读取失败仅影响观察，不把已确认发送改成未知失败。
async function refreshPushRecords() {
  if (loadingPushRecords.value) return;
  loadingPushRecords.value = true;
  try {
    pushRecords.value = (await analyticsApi.pushRecords()).data?.items || [];
    if (!manualReportId.value && manualAttempt.value) {
      const attempt = manualAttempt.value;
      const matches = pushRecords.value.filter((record) => record.period === attempt.period && record.channel === attempt.channel && Date.parse(record.createdAt) >= attempt.at - 2e3);
      if (matches.length === 1) manualReportId.value = matches[0].id;
    }
    const observed = pushRecords.value.find((record) => record.id === manualReportId.value);
    if (observed && ["sent", "failed"].includes(observed.status)) {
      localPushUncertain.value = false;
      manualPushKey.value = "";
    }
  } catch (error) {
    pushError.value = frontendError(error, "报表记录加载失败");
  } finally {
    loadingPushRecords.value = false;
  }
}
// 人工在目标群核查后登记结果；登记不会自行重新发送报表。
async function resolvePushRecord(record, outcome) {
  if (resolvingPush.value) return;
  try {
    await ElMessageBox.confirm(outcome === "sent" ? "确认已在目标群看到这份报表？" : "确认已在目标群核查这份报表未收到？", "记录报表核查", { confirmButtonText: "确认记录", cancelButtonText: "取消", type: "warning" });
  } catch {
    return;
  }
  resolvingPush.value = record.id;
  try {
    await analyticsApi.resolvePush(record.id, outcome);
    await refreshPushRecords();
    manualPushKey.value = "";
    ElMessage.success("报表核查结果已记录");
  } catch (error) {
    pushError.value = frontendError(error, "核查结果保存失败");
  } finally {
    resolvingPush.value = null;
  }
}
// 打开保留的旧版作品明细推送入口。
function openLegacyPush() {
  pushIds.value = [];
  pushResult.value = "";
  legacyPushDialog.value = true;
}
// 只有用户点击“发送数据”才调用外部推送，进入页面和刷新均不会发送。
async function pushData() {
  if (pushing.value || !pushIds.value.length) return;
  pushing.value = true;
  try {
    const result = await statsApi.pushContentStatsToDingTalk(pushAccounts.value.filter((item) => pushIds.value.includes(item.accountId)).map((item) => ({ accountId: item.accountId, platform: item.platform })));
    pushResult.value = result.msg || result.message || "推送请求已完成，请核对钉钉群接收结果";
    ElMessage.success(pushResult.value);
  } catch (error) {
    pushResult.value = frontendError(error, "推送失败");
  } finally {
    pushing.value = false;
  }
}
// 下载按当前筛选生成的 CSV，并释放临时附件地址。
async function exportData() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const response = await analyticsApi.exportCsv({ ...params(), entity: entity.value, sortBy: activeTab.value === "rankings" ? rankMetric.value : sortBy.value || void 0 });
    const url = URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url;
    link.download = `PostSail-${entity.value}-${dateRange.value?.[0] || ""}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1e3);
  } catch (error) {
    ElMessage.error(frontendError(error, "导出失败"));
  } finally {
    exporting.value = false;
  }
}
onMounted(refreshAll);
onBeforeUnmount(() => {
  alive = false;
  loadVersion++;
  metaVersion++;
});
</script>

<style scoped>
.analytics-workspace { max-width: 1700px; margin: 0 auto; color: #263346; }
.workspace-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.kicker { font-size: 12px; color: #8691a1; margin: 0 0 6px; }
h1 { font-size: 25px; letter-spacing: -.5px; margin: 0 0 8px; font-weight: 650; }
.description, .dialog-note { color: #778396; font-size: 13px; margin: 0; line-height: 1.6; }
.header-actions, .table-actions, .table-options { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.header-actions :deep(.el-button), .table-actions :deep(.el-button) { margin-left: 0; }
.filter-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 16px 0; border-top: 1px solid #e9edf2; }
.filter-bar :deep(.el-select) { width: 145px; }.filter-bar :deep(.el-select:nth-child(3)) { width: 200px; }.filter-bar :deep(.el-date-editor) { width: 285px; flex-grow: 0; }
.workspace-alert { margin: 0 0 12px; }.metric-strip { display: grid; grid-template-columns: repeat(6, 1fr); border-bottom: 1px solid #e9edf2; padding: 12px 0 26px; margin-bottom: 28px; }
.metric-cell { padding: 0 20px; border-right: 1px solid #e9edf2; }.metric-cell:first-child { padding-left: 0; }.metric-cell:last-child { border-right: 0; }.metric-cell > span { color: #7b8799; font-size: 13px; }.metric-cell strong { display: block; font-size: 27px; margin: 12px 0 8px; letter-spacing: -.6px; font-weight: 650; }.metric-cell small { color: #939bac; font-size: 11px; line-height: 1.5; }.metric-cell .positive { color: #208663; }.metric-cell .negative { color: #c46645; }
.section-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin: 0 0 18px; }.section-heading h2 { font-size: 16px; font-weight: 600; margin: 0; }.trend-chart { margin-bottom: 34px; }.muted, .scope-note { color: #919aac; font-size: 12px; }.scope-note { margin: 12px 0 16px; line-height: 1.7; }
.table-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 6px 0 18px; flex-wrap: wrap; }.table-options :deep(.el-input) { width: 250px; }.table-options :deep(.el-select) { width: 120px; }.column-picker :deep(.el-checkbox-group) { display: grid; grid-template-columns: 1fr 1fr; }.column-picker :deep(.el-checkbox) { margin-right: 8px; }
.unsupported-note { display: block; font-size: 11px; color: #919aac; margin-top: 4px; }.identity-cell strong, .work-cell strong { display: block; font-weight: 550; }.identity-cell small, .work-cell small { color: #8c96a5; font-size: 12px; }.work-cell { display: flex; align-items: center; gap: 12px; }.work-cell img { width: 38px; height: 50px; border-radius: 3px; object-fit: cover; }.work-cell strong { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; line-height: 1.5; }
.report-form :deep(.el-select), .report-form :deep(.el-time-editor) { width: 100%; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }.report-form .muted { display: block; line-height: 1.7; margin-top: 5px; }.push-save-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 22px; border-bottom: 1px solid #e9edf2; }.manual-report { padding: 22px 0; border-bottom: 1px solid #e9edf2; }.manual-report .section-heading { margin: 0 0 15px; }.manual-report .section-heading h2 { font-size: 14px; margin-bottom: 5px; }.manual-report .section-heading p { color: #8a95a5; font-size: 12px; margin: 0; }.manual-report-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 12px; }.push-history h3 { font-size: 14px; font-weight: 550; margin: 22px 0 12px; }.pagination { margin: 22px 0; display: flex; justify-content: space-between; align-items: center; gap: 12px; }.push-list { display: flex; flex-direction: column; margin: 20px 0; }.push-list :deep(.el-checkbox) { margin-right: 0; }.dialog-note { margin-bottom: 14px; }
@media (max-width: 1050px) { .workspace-header { align-items: flex-start; flex-direction: column; }.metric-strip { grid-template-columns: repeat(3, 1fr); row-gap: 24px; }.metric-cell:nth-child(4) { padding-left: 0; }.metric-cell:nth-child(3) { border-right: 0; } }
@media (max-width: 680px) { .form-grid { grid-template-columns: 1fr; gap: 0; }.push-save-row { align-items: flex-start; flex-direction: column; } .filter-bar { gap: 8px; }.filter-bar :deep(.el-select), .filter-bar :deep(.el-select:nth-child(3)) { width: calc(50% - 4px); }.filter-bar :deep(.el-date-editor) { width: 100%; }.metric-strip { grid-template-columns: repeat(2, 1fr); }.metric-cell:nth-child(odd) { padding-left: 0; border-right: 1px solid #e9edf2; }.metric-cell:nth-child(even) { border-right: 0; }.metric-cell strong { font-size: 24px; }.pagination { flex-direction: column; align-items: flex-start; }.table-options, .table-actions { width: 100%; }.table-options :deep(.el-input) { width: 100%; } }
</style>
