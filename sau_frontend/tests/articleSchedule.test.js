import test from 'node:test'
import assert from 'node:assert/strict'
import { scheduleForTask, schedulePayload, formatSchedule } from '../src/utils/articleSchedule.js'

test('排期请求保留用户选择的墙上时间，剔除 UI 开关', () => {
  assert.deepEqual(schedulePayload({ enabled: true, publish_at: '2030-01-02T10:00:00', timezone: 'Asia/Shanghai' }), {
    publish_at: '2030-01-02T10:00:00', timezone: 'Asia/Shanghai'
  })
  assert.throws(() => schedulePayload({ publish_at: '', timezone: 'UTC' }))
  assert.throws(() => schedulePayload({ publish_at: '2030-01-02T10:00:00', timezone: 'Wrong/Zone' }))
})

test('从服务器 UTC 按任务时区读回，不使用浏览器所在时区', () => {
  const task = { scheduled_at: '2030-01-02T02:00:00.000000+00:00', schedule_timezone: 'Asia/Shanghai' }
  assert.deepEqual(scheduleForTask(task), { publish_at: '2030-01-02T10:00:00+08:00', timezone: 'Asia/Shanghai' })
  assert.match(formatSchedule(task), /2030-01-02 10:00:00\+08:00 · Asia\/Shanghai/)
  assert.equal(formatSchedule({}), '立即发布')
})

test('夏令时回拨的两次相同时间保留各自偏移，改期不会悄悄改变时刻', () => {
  for (const [instant, local] of [
    ['2030-11-03T05:30:00.000000+00:00', '2030-11-03T01:30:00-04:00'],
    ['2030-11-03T06:30:00.000000+00:00', '2030-11-03T01:30:00-05:00']
  ]) {
    assert.deepEqual(scheduleForTask({ scheduled_at: instant, schedule_timezone: 'America/New_York' }), {
      publish_at: local, timezone: 'America/New_York'
    })
  }
})

test('午夜及非整点偏移可稳定读回', () => {
  assert.equal(scheduleForTask({ scheduled_at: '2030-01-01T16:00:00Z', schedule_timezone: 'Asia/Shanghai' }).publish_at, '2030-01-02T00:00:00+08:00')
  assert.equal(scheduleForTask({ scheduled_at: '2030-01-01T18:15:00Z', schedule_timezone: 'Asia/Kathmandu' }).publish_at, '2030-01-02T00:00:00+05:45')
})
