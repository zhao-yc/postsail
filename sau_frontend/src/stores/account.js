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
  9: '知乎'
}

export const useAccountStore = defineStore('account', () => {
  // 存储所有账号信息
  const accounts = ref([])

  const normalizeAccount = (item) => ({
    id: item[0],
    type: item[1],
    filePath: item[2],
    name: item[3],
    status: item[4] === -1 ? '验证中' : (item[4] === 1 ? '正常' : '异常'),
    platform: PLATFORM_TYPES[item[1]] || '未知'
  })

  // 设置账号列表
  const setAccounts = (accountsData) => {
    accounts.value = accountsData.map(normalizeAccount)
  }

  // 合并部分账号更新（按平台刷新时使用）
  const mergeAccounts = (accountsData) => {
    const updated = accountsData.map(normalizeAccount)
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
