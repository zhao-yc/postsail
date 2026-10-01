import request, { http } from '@/utils/request'

// 使用绝对地址保留 API 前缀，兼容 baseURL=/api 的开发代理与独立后端域名。
export function interactionUrl(path) {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
  const backend = new URL(request.defaults.baseURL || origin, origin)
  return new URL(path, backend).href
}
const base = interactionUrl('/api/interactions')
// 平台能力由后端报告，页面不根据发布支持列表推断评论或私信能力。
export const messagesApi = {
  capabilities: () => http.get(`${base}/capabilities`),
  accounts: () => http.get(`${base}/accounts`),
  messages: params => http.get(`${base}/messages`, params),
  detail: id => http.get(`${base}/messages/${id}`),
  mark: (id, state) => http.post(`${base}/messages/${id}/state`, state),
  reply: (id, data) => http.post(`${base}/messages/${id}/reply`, data, { timeout: 120000 }),
  resolve: (id, data) => http.post(`${base}/replies/${id}/resolve`, data),
  sync: data => http.post(`${base}/sync`, data),
  syncJob: id => http.get(`${base}/sync-jobs/${id}`),
  rules: () => http.get(`${base}/rules`),
  createRule: data => http.post(`${base}/rules`, data),
  updateRule: (id, data) => request.patch(`${base}/rules/${id}`, data),
  deleteRule: id => http.delete(`${base}/rules/${id}`),
  phrases: () => http.get(`${base}/phrases`),
  createPhrase: data => http.post(`${base}/phrases`, data),
  updatePhrase: (id, data) => request.patch(`${base}/phrases/${id}`, data),
  deletePhrase: id => http.delete(`${base}/phrases/${id}`),
  settings: () => http.get(`${base}/settings`),
  saveSettings: data => request.patch(`${base}/settings`, data),
  notifications: () => http.get(`${base}/notifications`)
}
