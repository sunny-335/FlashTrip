<script setup lang="ts">
/**
 * 三栏看板容器：左 DayColumn（可折叠/编辑/跨组拖拽）· 中 MapPane · 右 UnplannedPool。
 *  - PC（≥1024px）：三栏 grid，中间 minmax(0,1fr) 保证地图不被挤塌，父链每层都有明确高度；
 *  - 平板（768–1024px）：左右栏折叠为可展开抽屉，地图占满主区；
 *  - 手机（<768px）：地图 + 底部可切换的「已规划 / 待规划」面板，禁用拖拽改用排序按钮。
 *  持有 usePlanDnd 实例并通过 provide 注入子组件。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Loader2, ChevronRight, ListPlus, X, Sparkles, Wand2, AlertTriangle } from 'lucide-vue-next'
import { ApiError, postSSE } from '@/lib/api'
import { findLocalConflicts } from '@/lib/time'
import Button from '@/components/ui/Button.vue'
import Dialog from '@/components/ui/Dialog.vue'
import MapPane from '@/components/map/MapPane.vue'
import PlanToolbar from './PlanToolbar.vue'
import DayColumn from './DayColumn.vue'
import UnplannedPool from './UnplannedPool.vue'
import AddItemDialog from './AddItemDialog.vue'
import EditItemDialog from './EditItemDialog.vue'
import ImportDialog from './ImportDialog.vue'
import { providePlanContext, usePlanDnd } from '@/composables/usePlanDnd'
import { useUiStore } from '@/stores/ui'
import { usePlanStore } from '@/stores/plan'
import type { PlanItem, PlanType } from '@/stores/plan'

const props = withDefaults(defineProps<{ tripId: string; title?: string }>(), { title: '' })
const emit = defineEmits<{ requestDeleteTrip: [] }>()
const route = useRoute()
const dnd = usePlanDnd()
const ui = useUiStore()
const plan = usePlanStore()

// 断点：isMobile 直接读 ui store；isTablet 字段尚未由布局代理扩展时用 matchMedia 兜底
const mqMobile = ref(false)
const mqTablet = ref(false)
let mobileMql: MediaQueryList | null = null
let tabletMql: MediaQueryList | null = null
const syncMq = () => {
  mqMobile.value = mobileMql?.matches ?? false
  mqTablet.value = tabletMql?.matches ?? false
}
// 首屏同步读取，避免先按 PC 渲染再跳变；监听在挂载后注册、卸载时移除
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  mobileMql = window.matchMedia('(max-width: 768px)')
  tabletMql = window.matchMedia('(min-width: 769px) and (max-width: 1023px)')
  syncMq()
}
onMounted(() => {
  mobileMql?.addEventListener('change', syncMq)
  tabletMql?.addEventListener('change', syncMq)
})
onBeforeUnmount(() => {
  mobileMql?.removeEventListener('change', syncMq)
  tabletMql?.removeEventListener('change', syncMq)
})

const uiMaybeTablet = ui as unknown as { isTablet?: boolean }
const isMobile = computed(() => ui.isMobile || mqMobile.value)
const isTablet = computed(() => uiMaybeTablet.isTablet ?? mqTablet.value)
const isDesktop = computed(() => !isMobile.value && !isTablet.value)

const mobileTab = ref<'planned' | 'unplanned'>('planned')
const drawer = ref<'planned' | 'unplanned' | null>(null)

// 顶层 ref 绑定：模板会自动解包
const days = dnd.days
const allItems = dnd.allItems
const loadError = ref('')

const addOpen = ref(false)
const addType = ref<PlanType>('place')
const addDayId = ref<string | null>(null)
const importOpen = ref(false)
const importMode = ref<'file' | 'list'>('list')

// ---------------------------------------------------------------- 卡片完整修改弹窗
const editOpen = ref(false)
const editItem = ref<PlanItem | null>(null)
function openEdit(item: PlanItem) {
  editItem.value = item
  editOpen.value = true
}

// ---------------------------------------------------------------- 时间冲突重排
const rearrangeOpen = ref(false)
const rearrangeItem = ref<PlanItem | null>(null)
const rearranging = ref(false)
const rearrangeResult = ref('')
const rearrangeError = ref('')
const aiChatText = ref('')
const aiChatLoading = ref(false)
const aiChatError = ref('')
let aiController: AbortController | null = null

/** 该条目的行程日序号，用于「请帮我重排第 N 天」的中文提示。 */
const rearrangeDayIndex = computed(() => {
  const id = rearrangeItem.value?.day_id
  const day = id ? dnd.days.value.find((d) => d.id === id) : null
  return day?.day_index ?? null
})

/** 本地即时冲突提示：按「前项结束严格晚于后项开始」判定，首尾相接不算冲突。 */
const localConflictNote = computed(() => {
  const id = rearrangeItem.value?.day_id
  if (!id) return '该条目还在待规划池，请先排入某一天再重排时间。'
  const items = [...plan.planned, ...plan.unplanned].filter((i) => i.day_id === id)
  const hits = findLocalConflicts(items)
  return hits.length
    ? `本地即时检测到 ${hits.length} 处时间重叠（前一项 14:00 结束、后一项 14:00 开始首尾相接不算冲突）。`
    : '本地即时检测未发现时间重叠；前后两项首尾相接不算冲突。'
})

function openRearrange(item: PlanItem) {
  rearrangeItem.value = item
  rearrangeResult.value = ''
  rearrangeError.value = ''
  aiChatText.value = ''
  aiChatError.value = ''
  rearrangeOpen.value = true
}

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败，请重试'
}

/** 智能重排：POST /plan/auto-arrange（use_ai=true），成功后刷新 plan 与冲突。 */
async function autoArrange(): Promise<void> {
  const dayId = rearrangeItem.value?.day_id
  if (!dayId) {
    rearrangeError.value = '该条目还在待规划池，请先排入某一天再重排时间。'
    return
  }
  rearranging.value = true
  rearrangeError.value = ''
  rearrangeResult.value = ''
  try {
    const res = await plan.autoArrange(dayId, true)
    await dnd.reload()
    await plan.refreshConflicts()
    rearrangeResult.value = res.aiApplied ? '已由智能助手重排' : '已按顺序重排'
    if (typeof res.conflicts === 'number' && res.conflicts > 0) {
      rearrangeResult.value += `，仍有 ${res.conflicts} 处冲突`
    }
  } catch (e) {
    rearrangeError.value = messageOf(e)
  } finally {
    rearranging.value = false
  }
}

/** 交给智能助手：扁平 message + 页面上下文调用 POST /ai/chat，把 delta 显示在面板里。 */
function askAgent(): void {
  const item = rearrangeItem.value
  if (!item) return
  const n = rearrangeDayIndex.value ?? 1
  aiController?.abort()
  aiChatText.value = ''
  aiChatError.value = ''
  aiChatLoading.value = true
  aiController = postSSE('/ai/chat', {
    message: `请帮我重排第 ${n} 天的时间，消除冲突`,
    context: {
      scope: 'plan',
      tab: '行程',
      path: route.fullPath,
      trip_id: props.tripId,
      day_id: item.day_id,
      item_id: item.id,
    },
  }, {
    onEvent: (event, data) => {
      if (event === 'delta') {
        const d = (data ?? {}) as { delta?: string; content?: string }
        const chunk = typeof data === 'string' ? data : (d.delta ?? d.content ?? '')
        if (chunk) aiChatText.value += chunk
      } else if (event === 'error') {
        const d = (data ?? {}) as { message?: string }
        aiChatError.value = typeof data === 'string' ? data : (d.message || '智能助手返回错误')
      } else if (event === 'tool_result') {
        // 智能助手可能真的执行了重排工具，结束后统一刷新
      }
    },
    onError: (e) => {
      aiChatError.value = e.message
      aiChatLoading.value = false
    },
    onDone: () => {
      aiChatLoading.value = false
      void dnd.reload()
      void plan.refreshConflicts()
    },
  })
}

function closeRearrange(): void {
  rearrangeOpen.value = false
}

// 无论「关闭」按钮、ESC、点击遮罩或右上角 X 关闭，都统一中止未完成的 AI 流并归位状态
watch(rearrangeOpen, (v) => {
  if (v) return
  aiController?.abort()
  aiController = null
  aiChatLoading.value = false
})

onBeforeUnmount(() => aiController?.abort())

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

function onEdited(): void {
  void plan.refreshConflicts()
}

providePlanContext({ dnd, isMobile, openAdd, openImport, remove, openEdit, openRearrange })

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

/** 供 TripPlanView 的快捷键（Ctrl+N / Ctrl+Z）调用。 */
defineExpose({
  openAdd,
  undoLast: () => dnd.undoLast(),
})

onMounted(() => { void refresh() })
watch(() => props.tripId, () => { void refresh() })
</script>

<template>
  <div :class="isMobile
    ? 'flex min-h-[calc(100vh-3.5rem)] flex-col'
    : 'flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden'">
    <PlanToolbar :trip-id="tripId" :title="title" @request-delete-trip="emit('requestDeleteTrip')" />

    <div v-if="loadError" class="border-b border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
      {{ loadError }}
      <Button variant="ghost" size="sm" class="ml-2 h-6 px-2" @click="refresh">重试</Button>
    </div>

    <!-- PC：三栏 grid，中间列 minmax(0,1fr) 保证地图列不被内容挤塌 -->
    <div
      v-if="isDesktop"
      class="grid min-h-0 flex-1 grid-cols-[minmax(240px,280px)_minmax(0,1fr)_minmax(240px,300px)] gap-3 overflow-hidden p-3"
    >
      <div class="h-full min-h-0 space-y-3 overflow-y-auto">
        <DayColumn v-for="day in days" :key="day.id" :day="day" />
        <Button variant="outline" size="sm" class="w-full" @click="addDay">
          <Plus class="h-3.5 w-3.5" /> 添加一天
        </Button>
        <p v-if="!days.length" class="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted-foreground">
          还没有行程日，点上方「添加一天」建立第 1 天。
        </p>
      </div>

      <!-- 地图列：min-w-0 + h-full，父链每层都有明确高度，canvas 不会塌成 0 -->
      <div class="h-full min-h-0 min-w-0">
        <MapPane :items="allItems" class="h-full" />
      </div>

      <div class="h-full min-h-0 overflow-y-auto">
        <UnplannedPool class="min-h-full" />
      </div>
    </div>

    <!-- 平板：地图占满主区，左右栏折叠为可展开抽屉 -->
    <div v-else-if="isTablet" class="relative min-h-0 flex-1">
      <div class="absolute inset-0 p-3">
        <MapPane :items="allItems" class="h-full" />
      </div>

      <div class="absolute left-2 top-2 z-20 flex gap-1.5">
        <Button variant="outline" size="sm" @click="drawer = drawer === 'planned' ? null : 'planned'">
          <ChevronRight class="h-3.5 w-3.5" /> 已规划
        </Button>
        <Button variant="outline" size="sm" @click="drawer = drawer === 'unplanned' ? null : 'unplanned'">
          <ListPlus class="h-3.5 w-3.5" /> 待规划
        </Button>
      </div>

      <div
        v-if="drawer"
        class="absolute inset-y-0 left-0 z-30 flex w-[320px] max-w-[86%] flex-col border-r border-border bg-background shadow-lg"
      >
        <div class="flex items-center justify-between border-b border-border px-3 py-2">
          <span class="text-xs font-semibold">{{ drawer === 'planned' ? '已规划' : '待规划' }}</span>
          <Button variant="ghost" size="sm" class="h-7 px-2" @click="drawer = null">
            <X class="h-3.5 w-3.5" /> 收起
          </Button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto p-2">
          <div v-if="drawer === 'planned'" class="space-y-3">
            <DayColumn v-for="day in days" :key="day.id" :day="day" />
            <Button variant="outline" size="sm" class="w-full" @click="addDay">
              <Plus class="h-3.5 w-3.5" /> 添加一天
            </Button>
          </div>
          <UnplannedPool v-else class="h-full" />
        </div>
      </div>
    </div>

    <!-- 手机：地图 + 底部可切换面板；地图高度 min(45vh,360px) -->
    <div v-else class="flex min-h-0 flex-1 flex-col">
      <div class="shrink-0 p-2" :style="{ height: 'min(45vh, 360px)' }">
        <MapPane :items="allItems" class="h-full" />
      </div>
      <div class="flex shrink-0 items-center gap-1 border-y border-border bg-card px-2 py-1.5">
        <button
          class="flex-1 rounded-md px-3 py-1.5 text-xs"
          :class="mobileTab === 'planned' ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted'"
          @click="mobileTab = 'planned'"
        >已规划</button>
        <button
          class="flex-1 rounded-md px-3 py-1.5 text-xs"
          :class="mobileTab === 'unplanned' ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted'"
          @click="mobileTab = 'unplanned'"
        >待规划</button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto p-2" :style="{ height: '55vh' }">
        <div v-if="mobileTab === 'planned'" class="space-y-3">
          <DayColumn v-for="day in days" :key="day.id" :day="day" />
          <Button variant="outline" size="sm" class="w-full" @click="addDay">
            <Plus class="h-3.5 w-3.5" /> 添加一天
          </Button>
          <p v-if="!days.length" class="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted-foreground">
            还没有行程日，点上方「添加一天」建立第 1 天。
          </p>
        </div>
        <UnplannedPool v-else class="h-full" />
      </div>
    </div>

    <div v-if="dnd.busy.value" class="pointer-events-none fixed bottom-4 left-4 z-30 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-sm">
      <Loader2 class="h-3 w-3 animate-spin" /> 正在同步…
    </div>

    <AddItemDialog v-model="addOpen" :default-type="addType" :default-day-id="addDayId" />
    <ImportDialog v-model="importOpen" :mode="importMode" />
    <EditItemDialog v-model="editOpen" :item="editItem" @saved="onEdited" />

    <!-- 时间冲突重排：智能重排 + 交给智能助手（POST /ai/chat 带上下文，delta 就地显示） -->
    <Dialog v-model="rearrangeOpen" title="重排时间 · 消除冲突" description="选择一种方式处理同一天的时间冲突" width="max-w-md">
      <div class="space-y-3">
        <p class="rounded-lg border border-border bg-muted/30 px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
          <AlertTriangle class="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
          {{ localConflictNote }}
        </p>

        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Button variant="outline" size="sm" :disabled="rearranging || aiChatLoading" @click="autoArrange">
            <Loader2 v-if="rearranging" class="h-3.5 w-3.5 animate-spin" />
            <Wand2 v-else class="h-3.5 w-3.5" />
            智能重排
          </Button>
          <Button variant="outline" size="sm" :disabled="rearranging || aiChatLoading" @click="askAgent">
            <Loader2 v-if="aiChatLoading" class="h-3.5 w-3.5 animate-spin" />
            <Sparkles v-else class="h-3.5 w-3.5" />
            交给智能助手
          </Button>
        </div>

        <p v-if="rearrangeResult" class="rounded-lg border border-primary/30 bg-primary/5 px-2.5 py-2 text-xs text-foreground">
          {{ rearrangeResult }}
        </p>
        <p v-if="rearrangeError" class="rounded-lg border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
          {{ rearrangeError }}
        </p>

        <div v-if="aiChatText || aiChatError" class="space-y-1.5">
          <label class="text-xs font-medium">智能助手回复</label>
          <div class="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-card px-2.5 py-2 text-xs leading-relaxed text-foreground">{{ aiChatText }}</div>
          <p v-if="aiChatError" class="text-xs text-destructive">{{ aiChatError }}</p>
        </div>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" @click="closeRearrange">关闭</Button>
      </template>
    </Dialog>
  </div>
</template>
