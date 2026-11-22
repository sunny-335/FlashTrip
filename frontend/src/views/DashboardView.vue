<script setup lang="ts">
/** 仪表盘：当前行程、统计卡片、最近行程。数据来自 /trips 与 /trips/{id}/overview。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CalendarDays, MapPinned, ListChecks, Layers3, ArrowUpRight, Plus, Compass } from 'lucide-vue-next'
import { formatDate } from '@/lib/utils'
import { ApiError } from '@/lib/api'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useTripStore, type TripOverview } from '@/stores/trip'

const tripStore = useTripStore()
const router = useRouter()

const overview = ref<TripOverview | null>(null)
const loading = ref(true)
const error = ref('')

const statusLabel: Record<string, string> = {
  planned: '计划中', ongoing: '进行中', completed: '已完成', archived: '已归档',
}

const stats = computed(() => {
  const o = overview.value
  return [
    { label: '行程天数', value: o?.days_count ?? 0, icon: CalendarDays },
    { label: '计划条目', value: o?.item_count ?? 0, icon: ListChecks },
    { label: '已排入天', value: o?.planned_count ?? 0, icon: Layers3 },
    { label: '待规划池', value: o?.unplanned_count ?? 0, icon: Compass },
    { label: '已定位', value: o?.geocoded_count ?? 0, icon: MapPinned },
  ]
})

/** 优先取用户设置的当前行程；否则退回最近一条行程。 */
const focusTrip = computed(() => tripStore.currentTrip ?? tripStore.trips[0] ?? null)
const recentTrips = computed(() => tripStore.trips.slice(0, 5))

onMounted(async () => {
  try {
    await tripStore.load('all')
    const focus = tripStore.currentTrip ?? tripStore.trips[0]
    if (focus) overview.value = await tripStore.overview(focus.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    loading.value = false
  }
})

function openTrip(id: string) {
  void router.push(`/trips/${id}/plan`)
}
</script>

<template>
  <div class="mx-auto max-w-[1200px] space-y-5 px-5 py-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold">仪表盘</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">行程概览与最近动态</p>
      </div>
      <Button size="sm" @click="router.push('/trips')"><Plus class="h-3.5 w-3.5" /> 管理行程</Button>
    </div>

    <div v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</div>
    <div v-if="loading" class="py-16 text-center text-sm text-muted-foreground">正在加载行程数据…</div>

    <template v-else-if="!tripStore.trips.length">
      <EmptyState
        :icon="MapPinned"
        title="还没有任何行程"
        description="先建一条「周末去杭州」试试：把灵隐寺、西湖骑行、想住的民宿放进待规划池，再拖到 Day 1 / Day 2 排好顺序，地图上会自动连成路线。"
      >
        <Button size="sm" @click="router.push('/trips')"><Plus class="h-3.5 w-3.5" /> 新建第一条行程</Button>
      </EmptyState>
    </template>

    <template v-else>
      <!-- 统计卡片 -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Card v-for="s in stats" :key="s.label" class="flex items-center gap-3">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-primary">
            <component :is="s.icon" class="h-4 w-4" />
          </span>
          <div>
            <p class="text-lg font-semibold leading-tight">{{ s.value }}</p>
            <p class="text-[11px] text-muted-foreground">{{ s.label }}</p>
          </div>
        </Card>
      </div>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- 当前/焦点行程 -->
        <Card class="lg:col-span-2">
          <div class="mb-3 flex items-center justify-between">
            <h2 class="text-sm font-semibold">当前行程</h2>
            <span v-if="tripStore.currentTrip" class="text-[11px] text-muted-foreground">已设为当前</span>
          </div>
          <template v-if="focusTrip">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-base font-medium">{{ focusTrip.title }}</p>
                <p class="mt-1 text-xs text-muted-foreground">
                  {{ focusTrip.destination || '未填写目的地' }} ·
                  {{ formatDate(focusTrip.start_date) }} — {{ formatDate(focusTrip.end_date) }}
                </p>
              </div>
              <Badge :variant="focusTrip.status === 'completed' ? 'secondary' : 'default'">
                {{ statusLabel[focusTrip.status] ?? focusTrip.status }}
              </Badge>
            </div>
            <p v-if="overview" class="mt-3 text-xs text-muted-foreground">
              已排 {{ overview.planned_count }} / {{ overview.item_count }} 个条目，{{ overview.days_count }} 天行程，{{ overview.geocoded_count }} 个地点已定位。
            </p>
            <Button class="mt-4" size="sm" @click="openTrip(focusTrip.id)">
              打开行程规划 <ArrowUpRight class="h-3.5 w-3.5" />
            </Button>
          </template>
          <p v-else class="text-xs text-muted-foreground">暂无行程。</p>
        </Card>

        <!-- 最近行程 -->
        <Card>
          <h2 class="mb-3 text-sm font-semibold">最近行程</h2>
          <div class="space-y-1">
            <button
              v-for="t in recentTrips"
              :key="t.id"
              class="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-left hover:bg-muted"
              @click="openTrip(t.id)"
            >
              <span class="min-w-0">
                <span class="block truncate text-xs font-medium">{{ t.title }}</span>
                <span class="block truncate text-[11px] text-muted-foreground">{{ formatDate(t.start_date) }}</span>
              </span>
              <ArrowUpRight class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </button>
          </div>
        </Card>
      </div>
    </template>
  </div>
</template>
