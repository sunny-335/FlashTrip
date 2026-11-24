<script setup lang="ts">
/** 全站外壳：顶部主导航 / 行程导航、手机底部导航、全局 AI 入口。
 *  三端由 ui store 的真实断点驱动：手机底部栏 + 收窄顶栏，平板与桌面维持顶部导航。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Settings, LayoutDashboard, MapPinned, Images, ArrowLeft, Share2 } from 'lucide-vue-next'
import { ref } from 'vue'
import ShareDialog from '@/components/collab/ShareDialog.vue'
import { useToastStore } from '@/stores/toast'
import TopNavCenter from './TopNavCenter.vue'
import TripNavCenter from './TripNavCenter.vue'
import GlobalAgentFab from '@/components/agent/GlobalAgentFab.vue'
import RiskBanner from '@/components/common/RiskBanner.vue'
import { api } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const toast = useToastStore()
const shareOpen = ref(false)
const isTrip = computed(() => route.path.startsWith('/trips/'))
const showFab = computed(() => !route.path.startsWith('/settings') && !route.meta.hideAgent)
const hideForDetail = computed(() => Boolean(route.meta.hideBottomNav) || isTrip.value || route.path.startsWith('/share/'))
const showBottomNav = computed(() => ui.isMobile && !hideForDetail.value)
const isSharePage = computed(() => route.path.startsWith('/share/'))

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
  <!--
    外壳用 flex 列布局：header/main 为同一列，main 取剩余高度。
    若 main 用 min-h-screen，会与 56px 顶栏叠加出 56px 溢出，
    导致行程详情等整屏页面出现多余滚动条。
  -->
  <div class="flex min-h-screen flex-col overflow-x-hidden bg-background text-foreground">
    <header v-if="!ui.isMobile" class="sticky top-0 z-30 h-14 shrink-0 border-b border-border bg-card/90 backdrop-blur">
      <TripNavCenter v-if="isTrip" />
      <div v-else class="relative mx-auto grid h-full max-w-[1600px] grid-cols-[1fr_auto_1fr] items-center px-5">
        <RouterLink to="/dashboard" class="flex w-fit items-center gap-2 font-semibold tracking-tight">
          <img src="/logo.png" alt="瞬旅" class="h-7 w-7 rounded-md" />
          <span class="text-sm">瞬旅</span>
        </RouterLink>
        <div class="absolute left-1/2 h-full -translate-x-1/2"><TopNavCenter /></div>
        <div class="col-start-3 flex justify-self-end items-center gap-1">
          <RouterLink to="/settings" class="rounded-md p-2 text-muted-foreground hover:bg-muted" title="设置">
            <Settings class="h-4 w-4" />
          </RouterLink>
          <button class="rounded-md p-2 text-muted-foreground hover:bg-muted" title="退出登录" @click="logout">
            <LogOut class="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>

    <!-- 行程详情在手机端隐藏主导航后，保留返回与行程设置入口。 -->
    <div v-if="ui.isMobile && isTrip" class="sticky top-0 z-30 flex h-12 shrink-0 items-center justify-between border-b border-border bg-card/95 px-3 backdrop-blur">
      <button class="flex min-h-11 items-center gap-1 text-sm text-muted-foreground" @click="router.push('/trips')">
        <ArrowLeft class="size-4" /> 返回
      </button>
      <span class="truncate text-sm font-medium">{{ String(route.meta.title || '行程') }}</span>
      <button class="flex min-h-11 items-center gap-1 px-2 text-sm text-primary" @click="shareOpen = true">
        <Share2 class="size-4" /> 分享
      </button>
    </div>

    <!-- 手机端为底部导航栏预留安全区高度 -->
    <main
      class="min-h-0 flex-1"
      :style="showBottomNav ? { paddingBottom: 'calc(4rem + var(--safe-bottom))' } : undefined"
    >
      <slot />
    </main>

    <!-- 手机端底部导航栏 -->
    <nav v-if="showBottomNav" class="safe-bottom fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-card/95 backdrop-blur">
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

    <ShareDialog
      v-if="isTrip"
      v-model="shareOpen"
      :trip-id="String(route.params.tripId)"
      @created="toast.success('分享链接已创建')"
    />
    <GlobalAgentFab v-if="showFab" />
    <RiskBanner />
  </div>
</template>
