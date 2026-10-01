import axios from 'axios'
import request, { http } from '@/utils/request'

// 保留后端的 /api/analytics 前缀，避免相对开发代理地址重复拼接 /api。
export function analyticsUrl(path) {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
  const backend = new URL(request.defaults.baseURL || origin, origin)
  return new URL(path, backend).href
}

// 分析接口统一使用筛选对象，保留服务端返回的指标口径和数据覆盖信息。
export const analyticsApi = {
  capabilities: () => http.get(analyticsUrl('/api/analytics/capabilities')),
  overview: params => http.get(analyticsUrl('/api/analytics/overview'), params),
  accounts: params => http.get(analyticsUrl('/api/analytics/accounts'), params),
  works: params => http.get(analyticsUrl('/api/analytics/works'), params),
  owners: params => http.get(analyticsUrl('/api/analytics/owners'), params),
  rankings: params => http.get(analyticsUrl('/api/analytics/rankings'), params),
  accountSettings: () => http.get(analyticsUrl('/api/analytics/account-settings')),
  saveAccountSettings: data => http.put(analyticsUrl('/api/analytics/account-settings'), data),
  refreshAccount: (accountId, limit = 5) => http.post(analyticsUrl(`/api/analytics/accounts/${accountId}/refresh`), { limit }, { timeout: 180000 }),
  pushSettings: () => http.get(analyticsUrl('/api/analytics/push-settings')),
  savePushSettings: data => request.patch(analyticsUrl('/api/analytics/push-settings'), data),
  pushReport: data => http.post(analyticsUrl('/api/analytics/push'), data, { timeout: 120000 }),
  pushRecords: () => http.get(analyticsUrl('/api/analytics/push-records')),
  resolvePush: (id, outcome) => http.post(analyticsUrl(`/api/analytics/push-records/${id}/resolve`), { outcome }),

  // CSV 使用独立传输，避免统一 JSON 拦截器误判二进制附件；失败信息仍返回调用方。
  async exportCsv(params) {
    const token = localStorage.getItem('token')
    try {
      return await axios.get(analyticsUrl('/api/analytics/export'), {
        baseURL: request.defaults.baseURL, params, responseType: 'blob',
        headers: token ? { Authorization: `Bearer ${token}` } : {}, timeout: 60000
      })
    } catch (error) {
      if (error.response?.data instanceof Blob) {
        try { const body = JSON.parse(await error.response.data.text()); throw new Error(body.msg || body.message || '导出失败') }
        catch (parsedError) { if (!(parsedError instanceof SyntaxError)) throw parsedError }
      }
      throw error
    }
  }
}
