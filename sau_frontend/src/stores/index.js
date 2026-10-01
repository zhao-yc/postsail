import { createPinia } from 'pinia'
import { useAccountStore } from './account'
import { useAppStore } from './app'

const pinia = createPinia()

export default pinia
export { useAccountStore, useAppStore }
