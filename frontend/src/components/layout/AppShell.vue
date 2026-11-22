<script setup lang="ts">
/** 全站外壳：顶部主导航 / 行程导航、手机底部导航、全局 AI 入口。
 *  三端由 ui store 的真实断点驱动：手机底部栏 + 收窄顶栏，平板与桌面维持顶部导航。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Settings, LayoutDashboard, MapPinned, Images } from 'lucide-vue-next'
import TopNavCenter from './TopNavCenter.vue'
import TripNavCenter from './TripNavCenter.vue'
import GlobalAgentFab from '@/components/agent/GlobalAgentFab.vue'
import RiskBanner from '@/components/common/RiskBanner.vue'
import { api } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const isTrip = computed(() => route.path.startsWith('/trips/'))
const showFab = computed(() => !route.path.startsWith('/settings') && !route.meta.hideAgent)

const bottomItems = [
  { label: '仪表盘', path: '/dashboard', icon: LayoutDashboard },
  { label: '行程', path: '/trips', icon: MapPinned },
  { label: '记忆', path: '/memories', icon: Images },
  { label: '设置', path: '/settings', icon: Settings },
]

function isBottomActive(path: string): boolean {
  return route.path === path || (path !== '/dashboard' && route.path.startsWith(`${path}/`))
}

async function logout() {
  try { await api.post('/auth/logout') } catch { /* 忽略 */ }
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <header class="sticky top-0 z-30 h-14 border-b border-border bg-card/90 backdrop-blur">
      <TripNavCenter v-if="isTrip" />
      <div v-else class="mx-auto flex h-full max-w-[1600px] items-center gap-2 px-3 sm:gap-4 sm:px-5">
        <RouterLink to="/dashboard" class="flex shrink-0 items-center gap-2 font-semibold tracking-tight">
          <img src="/logo.png" alt="瞬旅" class="h-7 w-7 rounded-md" />
          <span class="text-sm">瞬旅</span>
        </RouterLink>
        <!-- 中央主导航在窄屏可横向滚动，不撑破顶栏 -->
        <div class="min-w-0 flex-1">
          <TopNavCenter />
        </div>
        <div class="flex shrink-0 items-center gap-0.5 sm:gap-1">
          <RouterLink to="/settings" class="rounded-md p-2 text-muted-foreground hover:bg-muted" title="设置">
            <Settings class="h-4 w-4" />
          </RouterLink>
          <button class="rounded-md p-2 text-muted-foreground hover:bg-muted" title="退出登录" @click="logout">
            <LogOut class="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>

    <!-- 手机端为底部导航栏预留安全区高度 -->
    <main
      class="min-h-[calc(100vh_-_3.5rem)]"
      :style="ui.isMobile ? { paddingBottom: 'calc(4rem + var(--safe-bottom))' } : undefined"
    >
      <slot />
    </main>

    <!-- 手机端底部导航栏 -->
    <nav v-if="ui.isMobile" class="safe-bottom fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-card/95 backdrop-blur">
      <RouterLink
        v-for="item in bottomItems"
        :key="item.path"
        :to="item.path"
        class="flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] transition-colors"
        :class="isBottomActive(item.path) ? 'text-primary' : 'text-muted-foreground hover:text-foreground'"
      >
        <component :is="item.icon" class="h-5 w-5" />
        {{ item.label }}
      </RouterLink>
    </nav>

    <GlobalAgentFab v-if="showFab" />
    <RiskBanner />
  </div>
</template>
