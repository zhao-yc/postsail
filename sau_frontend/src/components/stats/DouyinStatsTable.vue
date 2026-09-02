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
        <div class="traffic-expand" v-if="hasTrafficExpand(row)">
          <div class="metric-strip">
            <div class="metric-chip">
              <span class="metric-label">2s跳出率</span>
              <span class="metric-value">{{ formatPercent(row.bounceRate2s) }}</span>
            </div>
            <div class="metric-chip">
              <span class="metric-label">5s完播率</span>
              <span class="metric-value">{{ formatPercent(row.completionRate5s) }}</span>
            </div>
            <div class="metric-chip">
              <span class="metric-label">平均播放占比</span>
              <span class="metric-value">{{ formatPercent(row.avgPlayPercent) }}</span>
            </div>
          </div>

          <div class="dist-grid">
            <div class="dist-panel">
              <div class="dist-panel-title">性别分布</div>
              <div class="dist-panel-body">
                <template v-if="row.audienceGender && row.audienceGender.length">
                  <div
                    v-for="s in row.audienceGender"
                    :key="'g-' + s.name"
                    class="dist-row"
                  >
                    <span class="dist-name">{{ s.name }}</span>
                    <div class="dist-bar-track">
                      <div class="dist-bar-fill" :style="{ width: barWidth(s.ratio) }" />
                    </div>
                    <span class="dist-pct">{{ formatPercent(s.ratio) }}</span>
                  </div>
                </template>
                <div v-else class="dist-empty">暂无性别分布数据</div>
              </div>
            </div>

            <div class="dist-panel">
              <div class="dist-panel-title">年龄分布</div>
              <div class="dist-panel-body">
                <template v-if="row.audienceAge && row.audienceAge.length">
                  <div
                    v-for="s in row.audienceAge"
                    :key="'a-' + s.name"
                    class="dist-row"
                  >
                    <span class="dist-name">{{ s.name }}</span>
                    <div class="dist-bar-track">
                      <div class="dist-bar-fill" :style="{ width: barWidth(s.ratio) }" />
                    </div>
                    <span class="dist-pct">{{ formatPercent(s.ratio) }}</span>
                  </div>
                </template>
                <div v-else class="dist-empty">暂无年龄分布数据</div>
              </div>
            </div>

            <div class="dist-panel">
              <div class="dist-panel-title">地域分布</div>
              <div class="dist-panel-body dist-panel-body--scroll">
                <template v-if="row.audienceRegion && row.audienceRegion.length">
                  <div
                    v-for="s in row.audienceRegion"
                    :key="'r-' + s.name"
                    class="dist-row"
                  >
                    <span class="dist-name">{{ s.name }}</span>
                    <div class="dist-bar-track">
                      <div class="dist-bar-fill" :style="{ width: barWidth(s.ratio) }" />
                    </div>
                    <span class="dist-pct">{{ formatPercent(s.ratio) }}</span>
                  </div>
                </template>
                <div v-else class="dist-empty">暂无地域分布数据</div>
              </div>
            </div>

            <div class="dist-panel">
              <div class="dist-panel-title">流量来源</div>
              <div class="dist-panel-body">
                <template v-if="row.trafficSources && row.trafficSources.length">
                  <div
                    v-for="s in row.trafficSources"
                    :key="'t-' + s.name"
                    class="dist-row"
                  >
                    <span class="dist-name">{{ s.name }}</span>
                    <div class="dist-bar-track">
                      <div class="dist-bar-fill" :style="{ width: barWidth(s.ratio) }" />
                    </div>
                    <span class="dist-pct">{{ formatPercent(s.ratio) }}</span>
                  </div>
                </template>
                <div v-else class="dist-empty">暂无流量来源数据</div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="traffic-expand muted">暂无流量分析数据</div>
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
    <el-table-column prop="status" label="状态" width="100" />
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

function barWidth(ratio) {
  const n = Number(ratio)
  if (!Number.isFinite(n) || n <= 0) return '0%'
  return `${Math.min(100, n)}%`
}
</script>

<style scoped lang="scss">
.traffic-expand {
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

.metric-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.metric-chip {
  min-width: 120px;
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

.dist-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.dist-panel {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 12px;
  min-width: 0;
}

.dist-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.dist-panel-body--scroll {
  max-height: 9.6em;
  overflow-y: auto;
  padding-right: 2px;
}

.dist-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) 52px;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;

  &:last-child {
    margin-bottom: 0;
  }
}

.dist-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #606266;
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

.dist-empty {
  color: #909399;
  font-size: 12px;
  padding: 4px 0;
}

@media (max-width: 1099px) {
  .dist-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 759px) {
  .traffic-expand {
    margin-left: 16px;
  }

  .dist-grid {
    grid-template-columns: 1fr;
  }

  .metric-chip {
    flex: 1 1 140px;
  }
}
</style>
