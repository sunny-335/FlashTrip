<script setup lang="ts">
/** 行程列表：全部 / 未完成 / 已完成筛选（读 route.query.filter）、新建对话框、卡片进规划页。 */
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CalendarDays, MapPin, Plus, Loader2 } from 'lucide-vue-next'
import { formatDate } from '@/lib/utils'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { normalizeFilter, useTripStore, type TripCreate, type TripFilter, type TripStatus } from '@/stores/trip'

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

// query.filter 变化即重新拉取（TopNavCenter 的筛选链接也写同一 query）
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

// ---------------------------------------------------------------- 新建行程
const dialogOpen = ref(false)
const creating = ref(false)
const formError = ref('')
const form = reactive({
  title: '',
  destination: '',
  start_date: '',
  end_date: '',
  status: 'planned',
})
const statusOptions = [
  { value: 'planned', label: '计划中' },
  { value: 'ongoing', label: '进行中' },
  { value: 'completed', label: '已完成' },
]

function openCreate() {
  form.title = ''
  form.destination = ''
  form.start_date = ''
  form.end_date = ''
  form.status = 'planned'
  formError.value = ''
  dialogOpen.value = true
}

async function createTrip() {
  if (!form.title.trim()) {
    formError.value = '请填写行程标题'
    return
  }
  formError.value = ''
  creating.value = true
  const payload: TripCreate = {
    title: form.title.trim(),
    destination: form.destination.trim() || null,
    start_date: form.start_date || null,
    end_date: form.end_date || null,
    status: form.status as TripStatus,
  }
  try {
    const t = await tripStore.create(payload)
    dialogOpen.value = false
    await tripStore.load(filter.value)
    // 新建后立即进入规划页，可直接往待规划池添加地点
    await router.push(`/trips/${t.id}/plan`)
  } catch (e) {
    formError.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    creating.value = false
  }
}

const emptyText = computed(() =>
  filter.value === 'all'
    ? '还没有行程。新建一条「五一去成都」，把宽窄巷子、熊猫基地、想吃的火锅店先收进待规划池，再拖进各天。'
    : '该筛选下暂无行程，试试切换到「全部」。',
)

function openTrip(id: string) {
  void router.push(`/trips/${id}/plan`)
}
</script>

<template>
  <div class="mx-auto max-w-[1200px] space-y-5 px-5 py-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold">行程</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">管理你的全部旅程</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新建行程</Button>
    </div>

    <!-- 本地筛选（与顶部中央导航使用同一 query.filter） -->
    <div class="inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
      <button
        v-for="t in tabs"
        :key="t.k"
        class="rounded-md px-3 py-1.5 text-xs transition-colors"
        :class="filter === t.k ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
        @click="setFilter(t.k)"
      >{{ t.t }}</button>
    </div>

    <div v-if="tripStore.error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ tripStore.error }}
    </div>
    <div v-if="tripStore.loading" class="py-16 text-center text-sm text-muted-foreground">正在加载行程…</div>

    <template v-else-if="!tripStore.trips.length">
      <EmptyState :icon="MapPin" title="这里还空着" :description="emptyText">
        <Button v-if="filter === 'all'" size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新建行程</Button>
        <Button v-else variant="outline" size="sm" @click="setFilter('all')">查看全部</Button>
      </EmptyState>
    </template>

    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <button
        v-for="t in tripStore.trips"
        :key="t.id"
        class="group rounded-lg border border-border bg-card p-4 text-left shadow-sm transition hover:border-primary/50 hover:shadow-md"
        @click="openTrip(t.id)"
      >
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
      </button>
    </div>

    <!-- 新建行程对话框 -->
    <Dialog v-model="dialogOpen" title="新建行程" description="先填基本信息，创建后即可进入三栏规划页" width="max-w-md">
      <form class="space-y-3" @submit.prevent="createTrip">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">标题 <span class="text-destructive">*</span></label>
          <Input v-model="form.title" placeholder="例如：五一去成都" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">目的地</label>
          <Input v-model="form.destination" placeholder="例如：成都" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <label class="text-xs font-medium">开始日期</label>
            <Input v-model="form.start_date" type="date" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium">结束日期</label>
            <Input v-model="form.end_date" type="date" />
          </div>
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">状态</label>
          <Select v-model="form.status" :options="statusOptions" />
        </div>
        <div v-if="formError" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">
          {{ formError }}
        </div>
      </form>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="creating" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="creating" @click="createTrip">
          <Loader2 v-if="creating" class="h-3.5 w-3.5 animate-spin" />
          {{ creating ? '创建中…' : '创建并规划' }}
        </Button>
      </template>
    </Dialog>
  </div>
</template>
