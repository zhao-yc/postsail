import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import AccountManagement from '../views/AccountManagement.vue'
import MaterialManagement from '../views/MaterialManagement.vue'
import PublishCenter from '../views/PublishCenter.vue'
import ArticleManagement from '../views/ArticleManagement.vue'
import DataCenter from '../views/DataCenter.vue'
import AnalyticsCenter from '../views/AnalyticsCenter.vue'
import MessageCenter from '../views/MessageCenter.vue'
import About from '../views/About.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard
  },
  {
    path: '/account-management',
    name: 'AccountManagement',
    component: AccountManagement
  },
  {
    path: '/material-management',
    name: 'MaterialManagement',
    component: MaterialManagement
  },
  {
    path: '/publish-center',
    name: 'PublishCenter',
    component: PublishCenter
  },
  {
    path: '/articles',
    name: 'ArticleManagement',
    component: ArticleManagement
  },
  {
    path: '/data-center',
    name: 'DataCenter',
    component: AnalyticsCenter
  },
  {
    path: '/content-stats',
    name: 'ContentStats',
    component: DataCenter
  },
  {
    path: '/messages',
    name: 'Messages',
    component: MessageCenter
  },
  {
    path: '/about',
    name: 'About',
    component: About
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
