<template>
  <div class="schedule-fields">
    <label>时区</label>
    <el-select :model-value="modelValue.timezone" :disabled="disabled" filterable allow-create default-first-option aria-label="发布时间时区"
      @update:model-value="setTimezone">
      <el-option v-for="zone in zones" :key="zone" :label="zone" :value="zone" />
    </el-select>
    <label>发布时间（按所选时区填写）</label>
    <el-date-picker :model-value="modelValue.publish_at?.slice(0, 19) || ''" :disabled="disabled" type="datetime"
      value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" placeholder="选择未来时间"
      aria-label="定时发布时间" @update:model-value="setTime" />
    <small>到点开始提交，公开时间由平台审核决定。</small>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ modelValue: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const zones = computed(() => [...new Set([props.modelValue.timezone, 'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Singapore', 'UTC', 'Europe/London', 'America/New_York', 'America/Los_Angeles'].filter(Boolean))])
function setTime(value) { emit('update:modelValue', { ...props.modelValue, publish_at: value || '' }) }
function setTimezone(value) {
  emit('update:modelValue', { ...props.modelValue, timezone: value, publish_at: props.modelValue.publish_at?.slice(0, 19) || '' })
}
</script>

<style scoped>
.schedule-fields { display: grid; gap: 7px; min-width: 0; margin: 12px 0; }
.schedule-fields label { font-size: 12px; color: #66796d; }
.schedule-fields :deep(.el-select), .schedule-fields :deep(.el-date-editor) { width: 100%; min-width: 0; }
.schedule-fields small { font-size: 11px; color: #71817b; line-height: 1.7; }
</style>
