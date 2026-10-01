<template>
  <div ref="chartElement" class="trend-chart">
    <el-empty v-if="!availablePoints.length" description="尚无连续快照，可同步账号数据后查看趋势" :image-size="70" />
    <template v-else>
      <svg :viewBox="`0 0 ${chartWidth} 240`" role="img" :aria-label="`${label}趋势，${availablePoints.length} 个有效数据点`">
        <g v-for="tick in ticks" :key="tick.value" class="chart-grid">
          <line x1="58" :y1="tick.y" :x2="chartWidth - 18" :y2="tick.y" />
          <text x="48" :y="tick.y + 4" text-anchor="end">{{ formatNumber(tick.value) }}</text>
        </g>
        <path v-for="(segment, index) in segments" :key="index" :d="segment" class="chart-line" />
        <g v-for="point in coordinates" :key="point.index">
          <circle v-if="point.value != null" :cx="point.x" :cy="point.y" r="3.5" class="chart-point"><title>{{ point.date }}：{{ formatNumber(point.value) }}{{ point.intervalStart ? `，采样跨度 ${point.intervalStart} 至 ${point.intervalEnd}${point.crossesRangeStart ? '（跨越查询起点）' : ''}` : '' }}</title></circle>
          <text v-if="labelIndices.has(point.index)" :x="point.x" y="234" :text-anchor="point.index === 0 ? 'start' : point.index === points.length - 1 ? 'end' : 'middle'">{{ point.date }}</text>
        </g>
      </svg>
      <p class="chart-note">{{ label }} · {{ metric === 'publishedCount' ? '按作品发布时间统计。' : '按后一次采样日期归属，可能跨越查询起点，不代表自然日精确流量。' }}缺失数据不补零。</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'

const props = defineProps({ points: { type: Array, default: () => [] }, metric: { type: String, required: true }, label: { type: String, default: '数据' } })
const chartElement = ref(null), chartWidth = ref(900)
let resizeObserver = null

// 缺失值保留为空，避免将未采集的数据绘制成真实的零值。
const availablePoints = computed(() => props.points.filter(point => Number.isFinite(Number(point[props.metric])) && point[props.metric] != null))
const domain = computed(() => {
  const values = availablePoints.value.map(point => Number(point[props.metric]))
  const min = Math.min(0, ...values)
  const max = Math.max(...values, 1)
  return { min, max: max === min ? max + 1 : max }
})
const coordinates = computed(() => props.points.map((point, index) => {
  const raw = point[props.metric]
  const value = raw == null || !Number.isFinite(Number(raw)) ? null : Number(raw)
  return { index, date: point.date || point.day || '', value, intervalStart: point.intervalStart, intervalEnd: point.intervalEnd, crossesRangeStart: point.crossesRangeStart, x: 58 + index / Math.max(props.points.length - 1, 1) * (chartWidth.value - 76), y: value == null ? null : 202 - (value - domain.value.min) / (domain.value.max - domain.value.min) * 178 }
}))
// 将缺失日期处的折线分段，不用跨越空值的连线误导连续增长。
const segments = computed(() => {
  const paths = []
  let current = ''
  for (const point of coordinates.value) {
    if (point.value == null) { if (current) paths.push(current); current = ''; continue }
    current += `${current ? ' L' : 'M'} ${point.x} ${point.y}`
  }
  if (current) paths.push(current)
  return paths
})
const ticks = computed(() => Array.from({ length: 4 }, (_, index) => ({ value: domain.value.min + (domain.value.max - domain.value.min) * index / 3, y: 202 - index * 178 / 3 })))
const labelIndices = computed(() => new Set([0, Math.floor((props.points.length - 1) / 2), props.points.length - 1]))
function formatNumber(value) { return new Intl.NumberFormat('zh-CN', { notation: Math.abs(value) >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value) }
// 调整图表坐标空间而不是缩小所有文字，窄屏仍保留可读的轴标签。
onMounted(() => {
  const resize = () => { chartWidth.value = Math.min(900, Math.max(300, chartElement.value?.clientWidth || 900)) }
  resize()
  if (typeof ResizeObserver !== 'undefined') { resizeObserver = new ResizeObserver(resize); resizeObserver.observe(chartElement.value) }
})
onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<style scoped>
.trend-chart { min-height: 250px; }
svg { display: block; width: 100%; max-height: 270px; overflow: visible; }
.chart-grid line { stroke: #e8edf3; stroke-width: 1; }
text { font: 11px system-ui, sans-serif; fill: #8893a4; }
.chart-line { stroke: #3577ec; fill: none; stroke-width: 2.5; stroke-linejoin: round; }
.chart-point { fill: #3577ec; stroke: #fff; stroke-width: 1.5; }
.chart-note { color: #8b95a4; font-size: 12px; margin: 8px 0 0 58px; }
@media (max-width: 680px) { .trend-chart { min-height: 180px; } .chart-note { margin-left: 0; } }
</style>
