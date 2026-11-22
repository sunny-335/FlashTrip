<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Settings } from 'lucide-vue-next'
import TopNavCenter from './TopNavCenter.vue'
import TripNavCenter from './TripNavCenter.vue'
import GlobalAgentFab from '@/components/agent/GlobalAgentFab.vue'
import RiskBanner from '@/components/common/RiskBanner.vue'
import { api } from '@/lib/api'

const route = useRoute()
const router = useRouter()
const isTrip = computed(() => route.path.startsWith('/trips/'))
const showFab = computed(() => !route.path.startsWith('/settings') && !route.meta.hideAgent)

async function logout() {
  try { await api.post('/auth/logout') } catch { /* ignore */ }
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <header class="sticky top-0 z-30 h-14 border-b border-border bg-card/90 backdrop-blur">
      <TripNavCenter v-if="isTrip" />
      <div v-else class="mx-auto flex h-full max-w-[1600px] items-center px-5">
        <RouterLink to="/dashboard" class="flex w-40 shrink-0 items-center gap-2 font-semibold tracking-tight">
          <span class="inline-flex h-6 w-6 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs">瞬</span>
          瞬旅
        </RouterLink>
        <TopNavCenter />
        <div class="flex w-40 shrink-0 items-center justify-end gap-1">
          <RouterLink to="/settings" class="rounded-md p-2 text-muted-foreground hover:bg-muted" title="设置">
            <Settings class="h-4 w-4" />
          </RouterLink>
          <button class="rounded-md p-2 text-muted-foreground hover:bg-muted" title="退出登录" @click="logout">
            <LogOut class="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>

    <main class="min-h-[calc(100vh-3.5rem)]"><slot /></main>

    <GlobalAgentFab v-if="showFab" />
    <RiskBanner />
  </div>
</template>
