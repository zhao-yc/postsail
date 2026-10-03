import { defineStore } from 'pinia'
import { ref } from 'vue'

// 放在 store 外，避免 Pinia 对普通对象状态处理异常导致页面读到空映射
export const PLATFORM_TYPES = {
  1: '小红书',
  2: '视频号',
  3: '抖音',
  4: '快手',
  5: '百家号',
  6: 'B站',
  7: '今日头条',
  8: '搜狐',
  9: '知乎',
  10: '微博',
  11: '企鹅号',
  12: '一点号',
  13: '大鱼号',
  14: '网易号',
  15: 'AcFun',
  16: '快传号',
  17: '雪球号',
  18: '京东',
  19: '豆瓣',
  20: 'CSDN',
  21: '简书',
  22: '车家号',
  23: '易车号',
  24: '懂车号',
  25: '微信公众号',
  26: '京东图文',
  27: '小红书商家号',
  28: '淘宝光合'
}

export const ACCOUNT_UNAVAILABLE_REASONS = {}

export const useAccountStore = defineStore('account', () => {
  // 存储所有账号信息
  const accounts = ref([])

  const normalizeAccount = (item, identities = {}) => {
    const identity = identities[String(item[0])] || { needs_confirmation: item[1] >= 12 && item[1] <= 16 }
    return {
      id: item[0], type: item[1], filePath: item[2], name: item[3],
      status: identity.needs_confirmation ? '平台待确认' : (ACCOUNT_UNAVAILABLE_REASONS[item[1]] ? '待接入' : (item[4] === -1 ? '验证中' : (item[4] === 1 ? '正常' : '异常'))),
      platform: identity.needs_confirmation ? `待确认（旧编号 ${item[1]}）` : (PLATFORM_TYPES[item[1]] || '未知'),
      platformId: identity.platform, needsConfirmation: Boolean(identity.needs_confirmation),
      platformCandidates: identity.candidates || [], platformSuggestion: identity.suggested_platform,
      platformReason: identity.reason || '请确认旧账号实际所属平台'
    }
  }

  // 设置账号列表
  const setAccounts = (accountsData, identities = {}) => {
    accounts.value = accountsData.map(item => normalizeAccount(item, identities))
  }

  // 合并部分账号更新（按平台刷新时使用）
  const mergeAccounts = (accountsData, identities = {}) => {
    const updated = accountsData.map(item => normalizeAccount(item, identities))
    for (const acc of updated) {
      const index = accounts.value.findIndex(a => a.id === acc.id)
      if (index !== -1) {
        accounts.value[index] = acc
      } else {
        accounts.value.push(acc)
      }
    }
  }

  // 添加账号
  const addAccount = (account) => {
    accounts.value.push(account)
  }

  // 更新账号
  const updateAccount = (id, updatedAccount) => {
    const index = accounts.value.findIndex(acc => acc.id === id)
    if (index !== -1) {
      accounts.value[index] = { ...accounts.value[index], ...updatedAccount }
    }
  }

  // 删除账号
  const deleteAccount = (id) => {
    accounts.value = accounts.value.filter(acc => acc.id !== id)
  }

  // 根据平台获取账号
  const getAccountsByPlatform = (platform) => {
    return accounts.value.filter(acc => acc.platform === platform)
  }

  return {
    accounts,
    platformTypes: PLATFORM_TYPES,
    setAccounts,
    mergeAccounts,
    addAccount,
    updateAccount,
    deleteAccount,
    getAccountsByPlatform
  }
})
