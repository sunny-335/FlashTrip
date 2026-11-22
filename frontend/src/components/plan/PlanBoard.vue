<script setup lang="ts">
/**
 * 三栏看板容器：左 DayColumn（可折叠/编辑/跨组拖拽）· 中 MapPane · 右 UnplannedPool。
 * 持有 usePlanDnd 实例并通过 provide 注入给子组件；移动端单列堆叠 + 按钮排序。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Plus, Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import MapPane from '@/components/map/MapPane.vue'
import PlanToolbar from './PlanToolbar.vue'
import DayColumn from './DayColumn.vue'
import UnplannedPool from './UnplannedPool.vue'
import AddItemDialog from './AddItemDialog.vue'
import ImportDialog from './ImportDialog.vue'
import { providePlanContext, usePlanDnd } from '@/composables/usePlanDnd'
import { useUiStore } from '@/stores/ui'
import type { PlanType } from '@/stores/plan'

const props = withDefaults(defineProps<{ tripId: string; title?: string }>(), { title: '' })
const dnd = usePlanDnd()
const ui = useUiStore()
const isMobile = computed(() => ui.isMobile)

// 顶层 ref 绑定：模板会自动解包（直接写 dnd.days 不会解包）
const days = dnd.days
const allItems = dnd.allItems
const loadError = ref('')

const addOpen = ref(false)
const addType = ref<PlanType>('place')
const addDayId = ref<string | null>(null)
const importOpen = ref(false)
const importMode = ref<'file' | 'list'>('list')

function openAdd(type: PlanType, dayId: string | null = null) {
  addType.value = type
  addDayId.value = dayId
  addOpen.value = true
}
function openImport(mode: 'file' | 'list') {
  importMode.value = mode
  importOpen.value = true
}
function remove(id: string) {
  // 错误已写入 dnd.error，由 PlanToolbar 展示
  void dnd.deleteItem(id).catch(() => {})
}

providePlanContext({ dnd, isMobile, openAdd, openImport, remove })

async function refresh() {
  try {
    await dnd.load(props.tripId)
    loadError.value = ''
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : (e as Error).message
  }
}

async function addDay() {
  try {
    await dnd.addDay({})
    loadError.value = ''
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : (e as Error).message
  }
}

onMounted(() => { void refresh() })
watch(() => props.tripId, () => { void refresh() })
</script>

<template>
  <div class="flex min-h-[calc(100vh-3.5rem)] flex-col lg:h-[calc(100vh-3.5rem)]">
    <PlanToolbar :trip-id="tripId" :title="title" />

    <div v-if="loadError" class="border-b border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
      {{ loadError }}
      <Button variant="ghost" size="sm" class="ml-2 h-6 px-2" @click="refresh">重试</Button>
    </div>

    <div
      class="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[minmax(260px,1fr)_minmax(320px,1.3fr)_minmax(290px,1fr)] lg:overflow-hidden"
    >
      <!-- 左：按 Day 分组 -->
      <div class="space-y-3 lg:min-h-0 lg:overflow-y-auto">
        <DayColumn v-for="day in days" :key="day.id" :day="day" />
        <Button variant="outline" size="sm" class="w-full" @click="addDay">
          <Plus class="h-3.5 w-3.5" /> 添加一天
        </Button>
        <p v-if="!days.length" class="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted-foreground">
          还没有行程日，点上方「添加一天」建立 Day 1。
        </p>
      </div>

      <!-- 中：地图占位（M3 由地图模块替换） -->
      <div class="min-h-[320px] lg:min-h-0">
        <div class="h-[320px] lg:h-full">
          <MapPane :items="allItems" />
        </div>
      </div>

      <!-- 右：待规划池 -->
      <div class="min-h-[360px] lg:min-h-0">
        <UnplannedPool />
      </div>
    </div>

    <div v-if="dnd.busy.value" class="pointer-events-none fixed bottom-4 left-4 z-30 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-sm">
      <Loader2 class="h-3 w-3 animate-spin" /> 正在同步…
    </div>

    <AddItemDialog v-model="addOpen" :default-type="addType" :default-day-id="addDayId" />
    <ImportDialog v-model="importOpen" :mode="importMode" />
  </div>
</template>
