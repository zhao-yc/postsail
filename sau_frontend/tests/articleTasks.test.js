import assert from 'node:assert/strict'
import { test } from 'node:test'
import { notificationPlan, resolutionError, safeTaskUrl } from '../src/utils/articleTasks.js'

test('初次观察与恢复旧数据库不弹旧提醒', () => {
  const data = { latest_id: 12, items: [{ notification_id: 12 }] }
  assert.deepEqual(notificationPlan(null, data), { cursor: 12, items: [] })
  assert.deepEqual(notificationPlan(50, data), { cursor: 12, items: [] })
})
test('只提醒新事件，已读和已解决事件仍推进游标，重试后新异常可再次提醒', () => {
  assert.deepEqual(notificationPlan(12, { latest_id: 14, items: [{ notification_id: 14 }, { notification_id: 12 }] }), { cursor: 14, items: [{ notification_id: 14 }] })
  assert.deepEqual(notificationPlan(14, { latest_id: 15, items: [] }), { cursor: 15, items: [] })
  assert.deepEqual(notificationPlan(15, { latest_id: 16, items: [{ notification_id: 16, id: 'same-task' }] }).items, [{ notification_id: 16, id: 'same-task' }])
})
test('平台链接拒绝脚本和相对地址', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,x', '//example.com', 'https://', '/api/x']) assert.equal(safeTaskUrl(value), '')
  assert.equal(safeTaskUrl('https://example.com/articles/1'), 'https://example.com/articles/1')
})
test('核查始终需要说明，已受理任务只能凭公开链接确认发表', () => {
  assert.ok(resolutionError({ status: 'unknown' }, { note: ' ', resolution: 'not_published' }))
  assert.equal(resolutionError({ status: 'unknown' }, { note: '管理页没有文章', resolution: 'not_published' }), '')
  assert.ok(resolutionError({ status: 'submitted' }, { note: '核对过', resolution: 'not_published' }))
  assert.ok(resolutionError({ status: 'submitted' }, { note: '核对过', resolution: 'published' }))
  assert.equal(resolutionError({ status: 'submitted' }, { note: '公开页面正文正确', resolution: 'published', platform_url: 'https://example.com/article/1' }), '')
})
