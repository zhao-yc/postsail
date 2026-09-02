import { http } from '@/utils/request'

export const statsApi = {
  getContentStats(accountId, platform = 'douyin') {
    return http.get('/getContentStats', { accountId, platform })
  },
  syncContentStats(accountId, platform = 'douyin', limit = 5) {
    return http.post('/syncContentStats', { accountId, platform, limit }, {
      timeout: 120000
    })
  },
  pushContentStatsToDingTalk(accounts) {
    // accounts: [{ accountId, platform }, ...]
    return http.post('/pushContentStatsToDingTalk', { accounts }, {
      timeout: 180000
    })
  }
}
