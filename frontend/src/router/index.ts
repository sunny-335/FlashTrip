import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import PlaceholderView from '@/views/PlaceholderView.vue'

/**
 * 视图按需加载：import.meta.glob 只匹配磁盘上存在的文件，
 * 尚未实现的模块自动回退到 PlaceholderView，因此新增 View 无需修改路由表。
 * 约定：所有视图命名为 src/views/XxxView.vue。
 */
const modules = import.meta.glob('../views/*View.vue')
const view = (name: string) =>
  modules[`../views/${name}View.vue`] ?? (() => Promise.resolve({ default: PlaceholderView }))

const routes: RouteRecordRaw[] = [
  { path: '/install', name: 'install', component: view('Install'), meta: { standalone: true, title: '安装向导' } },
  { path: '/login', name: 'login', component: view('Login'), meta: { standalone: true, title: '登录' } },
  { path: '/invite/:token', name: 'invite', component: view('Invite'), meta: { standalone: true, title: '加入行程' } },
  // 公开分享页：独立渲染、无 AI 按钮，且不进入安装守卫与登录守卫
  { path: '/share/:token', name: 'share', component: view('Share'), meta: { standalone: true, public: true, hideAgent: true, title: '分享行程' } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: view('Dashboard'), meta: { title: '仪表盘' } },
  { path: '/footprints', name: 'footprints', component: view('Footprints'), meta: { title: '足迹' } },
  { path: '/memories', name: 'memories', component: view('Memories'), meta: { title: '记忆' } },
  { path: '/trips', name: 'trips', component: view('Trips'), meta: { title: '行程' } },
  { path: '/trips/:tripId/plan', name: 'trip-plan', component: view('TripPlan'), meta: { title: '行程规划' } },
  { path: '/trips/:tripId/bookings', name: 'trip-bookings', component: view('Bookings'), meta: { title: '预定' } },
  { path: '/trips/:tripId/transports', name: 'trip-transports', component: view('Transports'), meta: { title: '交通' } },
  { path: '/trips/:tripId/expenses', name: 'trip-expenses', component: view('Expenses'), meta: { title: '费用' } },
  { path: '/trips/:tripId/packing', name: 'trip-packing', component: view('Packing'), meta: { title: '物品' } },
  { path: '/trips/:tripId/moments', name: 'trip-moments', component: view('Moments'), meta: { title: '瞬间' } },
  // 足迹地图点击进入「该行程的记忆」：与全局记忆页共用视图，按 tripId 过滤
  { path: '/trips/:tripId/memories', name: 'trip-memories', component: view('Memories'), meta: { title: '行程记忆' } },
  { path: '/trips/:tripId/collab', name: 'trip-collab', component: view('Collab'), meta: { title: '协作' } },
  { path: '/settings', name: 'settings', component: view('Settings'), meta: { title: '设置', hideAgent: true } },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({ history: createWebHistory(), routes })

interface WizardStatus { installed: boolean; unlocked?: boolean }
let statusCache: WizardStatus | null = null

export async function wizardStatus(force = false): Promise<WizardStatus> {
  if (statusCache && !force) return statusCache
  try {
    const resp = await fetch('/api/v1/wizard/status', { credentials: 'same-origin' })
    const body = await resp.json()
    statusCache = {
      installed: Boolean(body?.data?.installed),
      unlocked: Boolean(body?.data?.unlocked),
    }
  } catch {
    statusCache = { installed: false }
  }
  return statusCache!
}

export function clearStatusCache() {
  statusCache = null
}

async function isAuthenticated(): Promise<boolean> {
  try {
    const resp = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
    return resp.ok
  } catch {
    return false
  }
}

router.beforeEach(async (to) => {
  // 公开页（分享行程）跳过安装守卫与登录守卫，未登录也可访问
  if (to.meta.public) return true
  const status = await wizardStatus()

  if (!status.installed) {
    return to.path === '/install' ? true : { path: '/install' }
  }
  if (to.path === '/install' && !status.unlocked) {
    return { path: '/login' }
  }
  if (to.meta.standalone) return true
  if (to.path === '/login') return true
  if (!(await isAuthenticated())) {
    return { path: '/login', query: { next: to.fullPath } }
  }
  return true
})

export default router
