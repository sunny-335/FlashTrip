<script setup lang="ts">
/** 行程列表：内容区下方做「全部 / 未完成 / 已完成」筛选（读 route.query.filter），
 *  新建 / 编辑走 TripFormDialog（含人数、儿童、家庭），删除用「是 / 否」二次确认。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CalendarDays, MapPin, Plus, Pencil, Trash2, Users, Baby, Home } from 'lucide-vue-next'
import { formatDate } from '@/lib/utils'
import { api, ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import TripFormDialog from '@/components/trip/TripFormDialog.vue'
import { normalizeFilter, useTripStore, type TripFilter, type Trip } from '@/stores/trip'

/** 列表接口实际返回 TripOut，含人数 / 家庭字段；本地扩展用于只读展示。 */
interface TripCard extends Trip {
  traveler_count?: number
  has_children?: boolean
  children_count?: number
  family_mode?: boolean
  family_name?: string | null
}

const route = useRoute()
const router = useRouter()
const tripStore = useTripStore()

const tabs: { k: TripFilter; t: string }[] = [
  { k: 'all', t: '全部' },
  { k: 'active', t: '未完成' },
  { k: 'completed', t: '已完成' },
]
const filter = ref<TripFilter>(normalizeFilter(route.query.filter))
const statusLabel: Record<string, string> = {
  planned: '计划中', ongoing: '进行中', completed: '已完成', archived: '已归档',
}

// query.filter 变化即重新拉取（顶部中央导航的筛选链接也写同一 query）
watch(
  () => route.query.filter,
  (v) => {
    filter.value = normalizeFilter(v)
    void tripStore.load(filter.value)
  },
  { immediate: true },
)

function setFilter(k: TripFilter) {
  void router.push({ path: '/trips', query: { filter: k } })
}

// ---------------------------------------------------------------- 新建 / 编辑行程
const formOpen = ref(false)
const editingTripId = ref<string | undefined>(undefined)

function openCreate() {
  editingTripId.value = undefined
  formOpen.value = true
}
function openEdit(id: string) {
  editingTripId.value = id
  formOpen.value = true
}
async function onSaved(tripId: string, created: boolean) {
  await tripStore.load(filter.value)
  if (created) await router.push(`/trips/${tripId}/plan`)
}

// ---------------------------------------------------------------- 删除行程（是 / 否 二次确认）
const deleteTarget = ref<TripCard | null>(null)
const deleting = ref(false)
const deleteError = ref('')

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await api.del(`/trips/${encodeURIComponent(deleteTarget.value.id)}`)
    deleteTarget.value = null
    await tripStore.load(filter.value)
  } catch (e) {
    deleteError.value = messageOf(e)
  } finally {
    deleting.value = false
  }
}

const emptyText = computed(() =>
  filter.value === 'all'
    ? '还没有行程。新建一条「五一去成都」，把宽窄巷子、熊猫基地、想吃的火锅店先收进待规划池，再拖进各天。'
    : '该筛选下暂无行程，试试切换到「全部」。',
)

/** 列表项按扩展类型读取人数 / 家庭字段（接口已返回，仅前端类型未声明）。 */
const cards = computed<TripCard[]>(() => tripStore.trips as TripCard[])

function openTrip(id: string) {
  void router.push(`/trips/${id}/plan`)
}

/** 人数摘要：成人数、儿童数与家庭模式一行展示。 */
function peopleText(t: TripCard): string {
  const total = Number(t.traveler_count) || 1
  const parts = [`${total} 人`]
  if (t.has_children && Number(t.children_count) > 0) parts.push(`含 ${t.children_count} 名儿童`)
  if (t.family_mode) parts.push(t.family_name ? `家庭：${t.family_name}` : '家庭模式')
  return parts.join(' · ')
}
</script>

<template>
  <div class="mx-auto max-w-[1200px] space-y-5 px-5 py-6">
    <div class="flex items-center justify-between">
      <div>
        <div class="flex flex-wrap items-center gap-3">
          <h1 class="text-lg font-semibold">行程</h1>
          <div class="inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
            <button v-for="t in tabs" :key="t.k" class="min-h-8 rounded-md px-2.5 text-[11px]" :class="filter === t.k ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted'" @click="setFilter(t.k)">{{ t.t }}</button>
          </div>
        </div>
        <p class="mt-0.5 text-xs text-muted-foreground">管理你的全部旅程</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新建行程</Button>
    </div>

    <div v-if="tripStore.error || deleteError" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ tripStore.error || deleteError }}
    </div>
    <div v-if="tripStore.loading" class="py-16 text-center text-sm text-muted-foreground">正在加载行程…</div>

    <template v-else-if="!tripStore.trips.length">
      <EmptyState :icon="MapPin" title="这里还空着" :description="emptyText">
        <Button v-if="filter === 'all'" size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新建行程</Button>
        <Button v-else variant="outline" size="sm" @click="setFilter('all')">查看全部</Button>
      </EmptyState>
    </template>

    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="t in cards"
        :key="t.id"
        class="flex flex-col rounded-lg border border-border bg-card shadow-sm transition hover:border-primary/50 hover:shadow-md"
      >
        <button class="flex-1 p-4 text-left" @click="openTrip(t.id)">
          <div class="flex items-start justify-between gap-2">
            <h3 class="truncate text-sm font-medium group-hover:text-primary">{{ t.title }}</h3>
            <Badge :variant="t.status === 'completed' ? 'secondary' : 'outline'">
              {{ statusLabel[t.status] ?? t.status }}
            </Badge>
          </div>
          <p v-if="t.destination" class="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
            <MapPin class="h-3.5 w-3.5" /> {{ t.destination }}
          </p>
          <p class="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
            <CalendarDays class="h-3.5 w-3.5" />
            {{ formatDate(t.start_date) }} — {{ formatDate(t.end_date) }}
          </p>
          <p class="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
            <Users class="h-3.5 w-3.5" /> {{ peopleText(t) }}
          </p>
        </button>
        <div class="flex justify-end gap-1.5 border-t border-border px-3 py-2">
          <Button variant="outline" size="sm" @click="openEdit(t.id)"><Pencil class="h-3.5 w-3.5" /> 编辑</Button>
          <Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" @click="deleteTarget = t"><Trash2 class="h-3.5 w-3.5" /> 删除</Button>
        </div>
      </div>
    </div>

    <!-- 单一筛选入口，避免列表顶部与底部重复。 -->
    <div class="flex flex-wrap items-center justify-center gap-2 border-t border-border pt-4">
      <span class="text-xs text-muted-foreground">按状态筛选</span>
      <div class="inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
        <button
          v-for="t in tabs"
          :key="t.k"
          class="min-h-9 rounded-md px-3 text-xs transition-colors"
          :class="filter === t.k ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          @click="setFilter(t.k)"
        >{{ t.t }}</button>
      </div>
    </div>

    <!-- 人数 / 儿童 / 家庭说明 -->
    <p class="flex items-center justify-center gap-1.5 text-[11px] text-muted-foreground">
      <Users class="h-3 w-3" /> 参加人数
      <Baby class="ml-1 h-3 w-3" /> 儿童
      <Home class="ml-1 h-3 w-3" /> 家庭分组，可在新建或编辑行程时设置
    </p>

    <TripFormDialog v-model="formOpen" :trip-id="editingTripId" @saved="(trip, created) => onSaved(trip.id, created)" />

    <ConfirmDialog
      :model-value="!!deleteTarget"
      title="确定要删除这个行程吗？"
      :message="deleteTarget ? `删除「${deleteTarget.title}」后，该行程及其内容将不再显示。` : '删除后该行程将不再显示。'"
      confirm-text="是"
      cancel-text="否"
      danger
      :busy="deleting"
      @update:model-value="(v) => { if (!v) deleteTarget = null }"
      @confirm="confirmDelete"
    />
  </div>
</template>
