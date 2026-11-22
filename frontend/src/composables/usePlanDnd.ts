/**
 * 三栏拖拽编排：
 * - 分组列表 lists：key 为 day.id 或 POOL_KEY，作为 VueDraggable 的 v-model。
 * - new_sort_key 由前端 keyBetween(before, after) 计算，后端仅做字典序校验。
 * - 乐观更新 + 失败回滚原数组；useUndoableMoves 维护命令栈，撤销快捷键统一在 TripPlanView 注册。
 * - 移动端不走 Sortable，改用 moveByButton 生成同样的 MoveIn。
 */
import {
  computed, inject, nextTick, provide, reactive, ref,
  type ComputedRef, type InjectionKey, type Ref,
} from 'vue'
import { ApiError } from '@/lib/api'
import { keyBetween, sortByKey } from '@/lib/sortKey'
import {
  usePlanStore,
  type MoveIn,
  type PlanItem,
  type PlanItemCreate,
  type PlanItemPatch,
  type PlanSnapshot,
  type PlanType,
  type TripDay,
} from '@/stores/plan'
import { useUndoableMoves } from './useUndoableMoves'

export const POOL_KEY = '__unplanned__'
export const DRAG_GROUP = 'flashtrip-plan'

/** vue-draggable-plus @end 透传的 Sortable 事件里我们需要的最小字段。 */
export interface DragEndEvent {
  item?: HTMLElement
  from?: HTMLElement
  to?: HTMLElement
  oldIndex?: number
  newIndex?: number
}

export type ButtonTarget =
  | { kind: 'up' }
  | { kind: 'down' }
  | { kind: 'to'; toKey: string }

function messageOf(e: unknown): string {
  if (e instanceof ApiError) return e.message
  return (e as Error)?.message || '操作失败，请重试'
}

/** 从 Sortable 目标容器读取分组 key；兼容组件 attr 透传与 closest 兜底。 */
function groupOfElement(el?: HTMLElement): string | undefined {
  if (!el) return undefined
  const direct = el.getAttribute('data-group')
  if (direct) return direct
  return el.closest?.('[data-group]')?.getAttribute('data-group') ?? undefined
}

export function usePlanDnd() {
  const store = usePlanStore()
  const commands = useUndoableMoves<PlanSnapshot>()

  /** day.id / POOL_KEY → 该组条目（按 sort_key 升序）。 */
  const lists = reactive<Record<string, PlanItem[]>>({})
  const error = ref('')
  const busy = ref(false)
  /** 是否正在拖拽：SortableJS @start 置真、@end 置假，卡片据此避免拖拽中误触发点击。 */
  const dragging = ref(false)
  /** 最近一次拖拽结束时间：用于抑制拖拽结束后浏览器补发的那一次 click。 */
  let lastDragEndAt = 0

  function onStartDrag(): void {
    dragging.value = true
  }
  function markDragEnd(): void {
    dragging.value = false
    lastDragEndAt = Date.now()
  }
  /** 拖拽刚结束的短时间内，整卡点击应被忽略，避免「拖完就弹出修改弹窗」。 */
  function wasJustDragged(): boolean {
    return dragging.value || Date.now() - lastDragEndAt < 300
  }

  const days = computed<TripDay[]>(() => store.days)
  const allItems = computed<PlanItem[]>(() => store.allItems)
  const canUndo = computed(() => commands.canUndo.value)

  /** 从 store 重建全部分组列表（每次写操作后调用，保证 v-model 与数据一致）。 */
  function rebuild(): void {
    for (const k of Object.keys(lists)) delete lists[k]
    for (const day of days.value) {
      lists[day.id] = sortByKey(store.planned.filter((i) => i.day_id === day.id))
    }
    lists[POOL_KEY] = sortByKey(store.unplanned)
  }

  async function load(tripId: string): Promise<void> {
    await store.load(tripId)
    commands.clear()
    rebuild()
  }

  /** 重新拉板但保留命令栈（撤销成功后与服务端对齐用）。 */
  async function reload(): Promise<void> {
    await store.load(store.tripId)
    rebuild()
  }

  function keyOfItem(id: string): string | null {
    for (const [k, list] of Object.entries(lists)) {
      if (list.some((i) => i.id === id)) return k
    }
    return null
  }

  /**
   * 依据「目标列表中该项的新位置」取相邻键生成 new_sort_key。
   * before/after 为 null 表示落在端点，直接交给 keyBetween 处理。
   */
  function buildMove(movedId: string, toKey: string, targetList: PlanItem[]): MoveIn | null {
    const idx = targetList.findIndex((i) => i.id === movedId)
    if (idx < 0) return null
    const beforeKey = idx > 0 ? targetList[idx - 1].sort_key : null
    const afterKey = idx < targetList.length - 1 ? targetList[idx + 1].sort_key : null
    let newSortKey: string
    try {
      newSortKey = keyBetween(beforeKey, afterKey)
    } catch (e) {
      error.value = `排序键计算失败：${messageOf(e)}`
      return null
    }
    return {
      item_id: movedId,
      to_day_id: toKey === POOL_KEY ? null : toKey,
      to_bucket: 'main',
      new_sort_key: newSortKey,
      before_sort_key: beforeKey,
      after_sort_key: afterKey,
    }
  }

  /** 提交一次移动：本地乐观 → 入命令栈 → POST /moves → 失败回滚原数组。 */
  async function submitMove(m: MoveIn, before: PlanSnapshot): Promise<void> {
    error.value = ''
    store.applyMovesLocal([m])
    rebuild()
    commands.push({ label: '移动条目', snapshot: before, moves: [m] })
    busy.value = true
    try {
      await store.move([m])
    } catch (e) {
      store.restore(before)
      rebuild()
      commands.pop()
      error.value = messageOf(e)
    } finally {
      busy.value = false
    }
  }

  /**
   * VueDraggable @end：不依赖 v-model 是否已跨容器更新（不同版本时机可能不同），
   * 而是剔除被拖条目后按 evt.newIndex 重新插入，得到稳定的目标顺序再算邻居键。
   * 此时 store 尚未乐观变更，故 snapshot 即为「拖拽前」快照。
   */
  async function onEnd(evt: DragEndEvent): Promise<void> {
    // 无论是否成功移动，都标记「刚拖拽过」，抑制随后补发的 click
    markDragEnd()
    const movedId = evt.item?.getAttribute('data-id')
    const domToKey = groupOfElement(evt.to)
    if (!movedId) {
      rebuild()
      return
    }
    // 让 v-model 的 update:modelValue（若有）先落地，避免读到半更新状态
    await nextTick()
    const toKey = domToKey ?? keyOfItem(movedId)
    const moved = store.findItem(movedId)
    if (!toKey || !lists[toKey] || !moved) {
      rebuild()
      return
    }
    const base = lists[toKey].filter((i) => i.id !== movedId)
    const newIndex = typeof evt.newIndex === 'number' && evt.newIndex >= 0 ? evt.newIndex : base.length
    const targetList = [...base]
    targetList.splice(Math.min(newIndex, base.length), 0, moved)

    const before = store.snapshot()
    const m = buildMove(movedId, toKey, targetList)
    if (!m) {
      rebuild()
      return
    }
    await submitMove(m, before)
  }

  /** 移动端上下 / 移至某天：构造期望顺序后复用同一套 MoveIn 提交逻辑。 */
  async function moveByButton(itemId: string, target: ButtonTarget): Promise<void> {
    const fromKey = keyOfItem(itemId)
    if (!fromKey) return
    const fromList = lists[fromKey]
    const idx = fromList.findIndex((i) => i.id === itemId)
    if (idx < 0) return
    const item = fromList[idx]

    let toKey = fromKey
    let targetList: PlanItem[]

    if (target.kind === 'to') {
      toKey = target.toKey
      targetList = [...(lists[toKey] ?? []).filter((i) => i.id !== itemId), item]
    } else {
      const rest = fromList.filter((i) => i.id !== itemId)
      const insertAt = target.kind === 'up'
        ? Math.max(0, idx - 1)
        : Math.min(rest.length, idx + 1)
      targetList = [...rest]
      targetList.splice(insertAt, 0, item)
    }

    const before = store.snapshot()
    const m = buildMove(itemId, toKey, targetList)
    if (!m) {
      error.value = error.value || '无法计算目标位置'
      return
    }
    await submitMove(m, before)
  }

  /** Ctrl+Z / 撤销按钮：乐观恢复快照 + POST /moves/undo，失败整体回滚。 */
  async function undoLast(): Promise<void> {
    const cmd = commands.pop()
    if (!cmd) return
    const current = store.snapshot()
    store.restore(cmd.snapshot)
    rebuild()
    busy.value = true
    try {
      await store.undo()
    } catch (e) {
      store.restore(current)
      rebuild()
      commands.push(cmd)
      error.value = messageOf(e)
      busy.value = false
      return
    }
    // 撤销已成功；重载失败只提示，不再回滚（否则与服务端不一致）
    try {
      await reload()
    } catch (e) {
      error.value = messageOf(e)
    } finally {
      busy.value = false
    }
  }

  // ---------------------------------------------------------------- 条目 / 行程日
  async function addItem(payload: PlanItemCreate): Promise<void> {
    error.value = ''
    try {
      const item = await store.addItem(payload)
      store.insertLocal(item)
      rebuild()
    } catch (e) {
      error.value = messageOf(e)
      throw e
    }
  }

  async function deleteItem(itemId: string): Promise<void> {
    error.value = ''
    const before = store.snapshot()
    store.removeLocal(itemId)
    rebuild()
    try {
      await store.deleteItem(itemId)
    } catch (e) {
      store.restore(before)
      rebuild()
      error.value = messageOf(e)
      throw e
    }
  }

  async function importItems(items: PlanItemCreate[]): Promise<number> {
    error.value = ''
    try {
      const created = await store.importItems(items)
      for (const it of created) store.insertLocal(it)
      rebuild()
      return created.length
    } catch (e) {
      error.value = messageOf(e)
      throw e
    }
  }

  async function addDay(payload: { date?: string | null; title?: string | null }): Promise<void> {
    const day = await store.addDay(payload)
    store.days.push(day)
    rebuild()
  }

  /** 折叠 / 标题 / 天气编辑：PUT 后用返回值合并本地 days。 */
  async function updateDay(
    dayId: string,
    patch: Partial<Pick<TripDay, 'title' | 'note' | 'weather_json' | 'collapsed' | 'date'>>,
  ): Promise<void> {
    const updated = await store.updateDay(dayId, patch)
    const idx = store.days.findIndex((d) => d.id === dayId)
    if (idx >= 0) store.days[idx] = { ...store.days[idx], ...updated }
  }

  /**
   * 编辑条目：乐观合并本地 → 真实 PUT → 用服务端返回值对齐；失败回滚原数组。
   * 快捷键统一由 TripPlanView 注册，本 composable 不再监听键盘。
   */
  async function updateItem(itemId: string, patch: PlanItemPatch): Promise<void> {
    error.value = ''
    const before = store.snapshot()
    const item = store.findItem(itemId)
    if (item) Object.assign(item, patch)
    rebuild()
    try {
      const updated = await store.updateItem(itemId, patch)
      store.replaceLocal(updated)
      rebuild()
    } catch (e) {
      store.restore(before)
      rebuild()
      error.value = messageOf(e)
      throw e
    }
  }

  return {
    lists, days, allItems, error, busy, canUndo, dragging,
    load, reload, rebuild, onEnd, onStartDrag, markDragEnd, wasJustDragged, moveByButton, undoLast,
    addItem, updateItem, deleteItem, importItems, addDay, updateDay,
  }
}

export type PlanDndApi = ReturnType<typeof usePlanDnd>

/** PlanBoard 向所有子组件注入的上下文，避免逐层 props/emit 转发。 */
export interface PlanContext {
  dnd: PlanDndApi
  isMobile: ComputedRef<boolean> | Ref<boolean>
  openAdd: (type: PlanType, dayId?: string | null) => void
  openImport: (mode: 'file' | 'list') => void
  remove: (id: string) => void
  /** 点击卡片：打开完整修改弹窗。 */
  openEdit: (item: PlanItem) => void
  /** 点击卡片时间区：打开重排操作（智能重排 / 交给智能助手）。 */
  openRearrange: (item: PlanItem) => void
}

export const PLAN_CTX: InjectionKey<PlanContext> = Symbol('flashtrip-plan-context')

export function providePlanContext(ctx: PlanContext): void {
  provide(PLAN_CTX, ctx)
}

export function usePlanContext(): PlanContext {
  const ctx = inject(PLAN_CTX, null)
  if (!ctx) throw new Error('PlanContext 未注入：请在 PlanBoard 内使用')
  return ctx
}
