<template>
  <el-table
    :data="items"
    row-key="itemId"
    v-loading="loading"
    stripe
    style="width: 100%"
    :empty-text="emptyText"
  >
    <el-table-column type="expand">
      <template #default="{ row }">
        <div class="ks-expand" v-if="hasTrafficExpand(row)">
          <div v-if="row.boostPlayCount != null && row.boostPlayCount > 0" class="boost-banner">
            <div class="boost-main">
              流量助推 累计
              <span class="boost-num">{{ row.boostPlayCount }}</span>
              次额外播放
            </div>
            <div v-if="row.boostReason" class="boost-reason">{{ row.boostReason }}</div>
          </div>

          <div class="metric-strip">
            <div class="metric-chip">
              <span class="metric-label">2s 跳出率</span>
              <span class="metric-value">{{ formatPercent(row.bounceRate2s) }}</span>
            </div>
            <div class="metric-chip">
              <span class="metric-label">5s 完播率</span>
              <span class="metric-value">{{ formatPercent(row.completionRate5s) }}</span>
            </div>
            <div class="metric-chip">
              <span class="metric-label">完播率</span>
              <span class="metric-value">{{ formatPercent(row.completionRate) }}</span>
            </div>
            <div class="metric-chip">
              <span class="metric-label">平均时长</span>
              <span class="metric-value">{{
                row.avgPlayDurationSec != null ? `${row.avgPlayDurationSec}秒` : '—'
              }}</span>
            </div>
            <div v-if="row.avgPlayPercent != null" class="metric-chip">
              <span class="metric-label">平均播放占比</span>
              <span class="metric-value">{{ formatPercent(row.avgPlayPercent) }}</span>
            </div>
          </div>

          <div class="detail-grid">
            <div class="panel">
              <div class="panel-title">内容诊断</div>
              <template v-if="row.contentDiagnose && row.contentDiagnose.length">
                <div class="diagnose-grid">
                  <div
                    v-for="d in row.contentDiagnose"
                    :key="d.dimension || d.title"
                    class="diagnose-card"
                  >
                    <div class="diagnose-score" :class="scoreTone(d.score)">{{ d.score }}</div>
                    <div class="diagnose-copy">
                      <div class="diagnose-name">{{ shortDiagnoseTitle(d.title) }}</div>
                      <div v-if="d.desc" class="diagnose-desc">{{ d.desc }}</div>
                    </div>
                  </div>
                </div>
              </template>
              <div v-else class="panel-empty">暂无内容诊断</div>
            </div>

            <div class="panel">
              <div class="panel-title">流量来源</div>
              <template v-if="row.trafficSources && row.trafficSources.length">
                <div
                  v-for="s in row.trafficSources"
                  :key="'src-' + s.name"
                  class="dist-row"
                >
                  <span class="dist-name">{{ s.name }}</span>
                  <div class="dist-bar-track">
                    <div class="dist-bar-fill" :style="{ width: barWidth(s.ratio) }" />
                  </div>
                  <span class="dist-pct">{{ formatPercent(s.ratio) }}</span>
                </div>
              </template>
              <div v-else class="panel-empty">暂无流量来源数据</div>
            </div>
          </div>

          <div v-if="row.metricTrends && row.metricTrends.length" class="panel trend-panel">
            <div class="panel-title">趋势（按小时）</div>
            <div class="trend-grid">
              <div v-for="s in row.metricTrends" :key="s.key" class="trend-card">
                <div class="trend-card-head">
                  <span>{{ s.name }}</span>
                  <span class="trend-last">{{ formatTrendValue(s) }}</span>
                </div>
                <svg class="trend-spark" viewBox="0 0 220 48" preserveAspectRatio="none">
                  <polygon
                    :points="sparklineArea(s.points)"
                    fill="rgba(64, 158, 255, 0.12)"
                  />
                  <polyline
                    :points="sparklineLine(s.points)"
                    fill="none"
                    stroke="#409eff"
                    stroke-width="1.8"
                    stroke-linejoin="round"
                    stroke-linecap="round"
                  />
                </svg>
                <div v-if="s.points && s.points.length" class="trend-range">
                  {{ shortTime(s.points[0].date) }} – {{ shortTime(s.points[s.points.length - 1].date) }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="ks-expand muted">暂无流量分析数据</div>
      </template>
    </el-table-column>
    <el-table-column label="封面" width="100">
      <template #default="{ row }">
        <el-image
          v-if="row.coverUrl"
          :src="displayCoverUrl(row.coverUrl)"
          fit="cover"
          style="width: 64px; height: 64px; border-radius: 4px"
          :preview-src-list="[displayCoverUrl(row.coverUrl)]"
          referrer-policy="no-referrer"
          preview-teleported
          hide-on-click-modal
        />
        <span v-else>—</span>
      </template>
    </el-table-column>
    <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
    <el-table-column prop="publishedAt" label="发布时间" width="170" />
    <el-table-column prop="status" label="状态" width="120" show-overflow-tooltip />
    <el-table-column prop="playCount" label="浏览" width="90" />
    <el-table-column prop="likeCount" label="点赞" width="90" />
    <el-table-column prop="commentCount" label="评论" width="90" />
    <el-table-column prop="shareCount" label="分享" width="90" />
    <el-table-column prop="collectCount" label="收藏" width="90" />
    <el-table-column label="完播率" width="100">
      <template #default="{ row }">
        {{ formatPercent(row.completionRate) }}
      </template>
    </el-table-column>
    <el-table-column label="平均时长" width="100">
      <template #default="{ row }">
        {{ row.avgPlayDurationSec != null ? `${row.avgPlayDurationSec}秒` : '—' }}
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无作品' },
  displayCoverUrl: { type: Function, required: true },
  formatPercent: { type: Function, required: true },
  hasTrafficExpand: { type: Function, required: true },
})

const SPARK_W = 220
const SPARK_H = 48
const SPARK_PAD = 3

function shortDiagnoseTitle(title) {
  return String(title || '').replace(/评估$/, '')
}

function scoreTone(score) {
  const n = Number(score)
  if (!Number.isFinite(n)) return 'is-mid'
  if (n >= 70) return 'is-high'
  if (n >= 50) return 'is-mid'
  return 'is-low'
}

function lastTrendPoint(points) {
  if (!points || !points.length) return null
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const v = Number(points[i].value)
    if (Number.isFinite(v) && v !== 0) return points[i]
  }
  return points[points.length - 1]
}

function formatTrendValue(series) {
  const point = lastTrendPoint(series && series.points)
  if (!point) return '—'
  const v = point.value
  if (v === null || v === undefined || v === '') return '—'
  if (series.key === 'AVG_PLAY_DURATION') return `${v}秒`
  if (series.key === 'PLAY_CNT') return v
  return `${v}%`
}

function sparkCoords(points) {
  if (!points || !points.length) return []
  const vals = points.map((p) => Number(p.value) || 0)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  return vals.map((v, i) => {
    const x = points.length === 1 ? SPARK_W / 2 : (i / (points.length - 1)) * SPARK_W
    const y = SPARK_H - SPARK_PAD - ((v - min) / span) * (SPARK_H - SPARK_PAD * 2)
    return { x, y }
  })
}

function sparklineLine(points) {
  return sparkCoords(points).map((p) => `${p.x},${p.y}`).join(' ')
}

function sparklineArea(points) {
  const coords = sparkCoords(points)
  if (!coords.length) return ''
  const line = coords.map((p) => `${p.x},${p.y}`).join(' ')
  return `0,${SPARK_H} ${line} ${SPARK_W},${SPARK_H}`
}

function shortTime(raw) {
  const s = String(raw || '')
  const m = s.match(/(\d{2})-(\d{2}) (\d{2}:\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}`
  return s.replace(/:\d{2}$/, '')
}

function barWidth(ratio) {
  const n = Number(ratio)
  if (!Number.isFinite(n) || n <= 0) return '0%'
  return `${Math.min(100, n)}%`
}
</script>

<style scoped lang="scss">
.ks-expand {
  margin: 4px 12px 12px 48px;
  padding: 12px 14px;
  background: #f5f7fa;
  border-radius: 6px;
  color: #606266;
  font-size: 13px;
  line-height: 1.5;

  &.muted {
    color: #909399;
    background: transparent;
    padding-left: 0;
  }
}

.boost-banner {
  margin-bottom: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #fde2e2;
  border-radius: 6px;
}

.boost-main {
  color: #303133;
}

.boost-num {
  color: #e94e5b;
  font-weight: 700;
  margin: 0 2px;
  font-variant-numeric: tabular-nums;
}

.boost-reason {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}

.metric-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.metric-chip {
  min-width: 112px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-label {
  font-size: 12px;
  color: #909399;
}

.metric-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  font-variant-numeric: tabular-nums;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 10px;
  margin-bottom: 10px;
}

.panel {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 12px;
  min-width: 0;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.panel-empty {
  color: #909399;
  font-size: 12px;
  padding: 4px 0;
}

.diagnose-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.diagnose-card {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.diagnose-score {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  padding-top: 2px;

  &.is-high { color: #67c23a; }
  &.is-mid { color: #e6a23c; }
  &.is-low { color: #e94e5b; }
}

.diagnose-name {
  color: #303133;
  font-weight: 600;
  font-size: 13px;
}

.diagnose-desc {
  margin-top: 2px;
  color: #909399;
  font-size: 12px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.dist-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) 56px;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;

  &:last-child { margin-bottom: 0; }
}

.dist-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dist-bar-track {
  height: 6px;
  background: #ebeef5;
  border-radius: 999px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  background: #409eff;
  border-radius: 999px;
}

.dist-pct {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #303133;
  font-size: 12px;
}

.trend-panel {
  margin-bottom: 0;
}

.trend-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}

.trend-card {
  min-width: 0;
  padding: 6px 2px 2px;
}

.trend-card-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: #909399;
}

.trend-last {
  color: #303133;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.trend-spark {
  display: block;
  width: 100%;
  height: 48px;
  margin-top: 6px;
}

.trend-range {
  margin-top: 2px;
  color: #c0c4cc;
  font-size: 11px;
}

@media (max-width: 1099px) {
  .detail-grid,
  .diagnose-grid,
  .trend-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 759px) {
  .ks-expand {
    margin-left: 16px;
  }
}
</style>
