import request from '@/utils/request'

// 文章接口保留 /api 前缀；将素材与证据地址解析到同一后端，避免落到前端端口。
export const articleUrl = (path) => {
  if (!path) return ''
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
  const base = new URL(request.defaults.baseURL || origin, origin)
  return new URL(path, base).href
}

// 文章工作台与 CLI 使用相同协议，沿用现有请求拦截器及登录凭据。
export const articlesApi = {
  list: () => request.get(articleUrl('/api/articles')),
  get: (id) => request.get(articleUrl(`/api/articles/${id}`)),
  create: (data) => request.post(articleUrl('/api/articles'), data),
  update: (id, data) => request.patch(articleUrl(`/api/articles/${id}`), data),
  capabilities: () => request.get(articleUrl('/api/article-capabilities')),
  accounts: () => request.get(articleUrl('/api/article-accounts')),
  uploadAsset: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request.post(articleUrl('/api/article-assets'), form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  importAsset: (url) => request.post(articleUrl('/api/article-assets'), { url }),
  publish: (id, data) => request.post(articleUrl(`/api/articles/${id}/publish`), data),
  batches: (articleId) => request.get(articleUrl('/api/article-publish-batches'), {
    params: { article_id: articleId }
  }),
  batch: (id) => request.get(articleUrl(`/api/article-publish-batches/${id}`)),
  retry: (id) => request.post(articleUrl(`/api/article-publish-tasks/${id}/retry`), {}),
  pending: (page = 1, pageSize = 20) => request.get(articleUrl('/api/article-publish-tasks'), { params: { page, page_size: pageSize } }),
  reschedule: (id, data) => request.patch(articleUrl(`/api/article-publish-tasks/${id}/schedule`), data),
  cancel: (id, revision) => request.post(articleUrl(`/api/article-publish-tasks/${id}/cancel`), { expected_schedule_revision: revision }),
  resolve: (id, data) => request.post(articleUrl(`/api/article-publish-tasks/${id}/resolve`), data)
}
