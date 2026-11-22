/** 三栏计划板数据 + API。字段严格对齐 schemas/plan.py 与 TripDayOut。
 *  所有写操作都立即请求后端（不做「只改本地」的假保存），并通过 dirty / flush()
 *  让页面在离开时等待全部写请求落库，避免「点击返回就没了」。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/lib/api'
import { sortByKey } from '@/lib/sortKey'
import { findLocalConflicts } from '@/lib/time'

export type PlanType = 'place' | 'hotel' | 'transport' | 'activity' | 'note'

/** PlanItemOut：day_id 为 null 表示在「待规划池」。 */
export interface PlanItem {
  id: string
  trip_id: string
  day_id: string | null
  bucket: string
  type: string
  title: string
  subtitle: string | null
  address: string | null
  category: string | null
  lng: number | null
  lat: number | null
  coord_system: string
  start_time: string | null
  end_time: string | null
  duration_min: number | null
  note: string | null
  payload_json: string | null
  source: string
  external_id: string | null
  sort_key: string
  created_by: string | null
  created_at: string | null
}

export interface TripDay {
  id: string
  trip_id: string
  day_index: number
  date: string | null
  title: string | null
  note: string | null
  weather_json: string | null
  collapsed: boolean
  sort_key: string
  created_at: string | null
}

/** PlanItemCreate：新增/导入条目请求体。 */
export interface PlanItemCreate {
  day_id?: string | null
  bucket?: string
  type?: PlanType
  title: string
  subtitle?: string | null
  address?: string | null
  category?: string | null
  lng?: number | null
  lat?: number | null
  coord_system?: string
  start_time?: string | null
  end_time?: string | null
  duration_min?: number | null
  note?: string | null
  payload_json?: string | null
  source?: string
  external_id?: string | null
  sort_key?: string | null
}

/** 编辑条目的可补丁字段，对齐后端 PlanItemUpdate（datetime 以字符串传输）。 */
export type PlanItemPatch = Partial<PlanItemCreate>

/** MoveIn：new_sort_key 由前端 keyBetween 生成，后端仅做字典序校验。 */
export interface MoveIn {
  item_id: string
  to_day_id: string | null
  to_bucket: string
  new_sort_key: string
  before_sort_key: string | null
  after_sort_key: string | null
}

export interface PlanData {
  days: TripDay[]
  planned: PlanItem[]
  unplanned: PlanItem[]
  planned_by_day?: Record<string, PlanItem[]>
}

export interface PlanSnapshot {
  planned: PlanItem[]
  unplanned: PlanItem[]
}

export interface MoveResult { batch_id: string; moved: number }
export interface UndoResult { batch_id: string; restored: number }

/** GET /plan/categories 的中文预设分类。 */
export interface PlanCategory { id: string; label: string }

/** 接口加载失败时的本地兜底：8 个中文预设，保证分类下拉不空白。 */
export const DEFAULT_CATEGORIES: PlanCategory[] = [
  { id: '景点', label: '景点' },
  { id: '餐饮', label: '餐饮' },
  { id: '住宿', label: '住宿' },
  { id: '交通', label: '交通' },
  { id: '购物', label: '购物' },
  { id: '娱乐', label: '娱乐' },
  { id: '休闲', label: '休闲' },
  { id: '其他', label: '其他' },
]

/** GET /plan/conflicts 的一条冲突：同一行程日内前项结束严格晚于后项开始。 */
export interface PlanConflict {
  item_id: string
  with_item_id: string
  start: string
  end: string
  reason: string
}

/** POST /plan/auto-arrange 的返回。 */
export interface AutoArrangeResult {
  arranged: number
  dayId: string
  useAi: boolean
  aiApplied: boolean
  conflicts: number
  items: { id: string; start_time: string | null; end_time: string | null; duration_min: number | null }[]
}

/** POST /weather-advice 的返回。 */
export interface WeatherAdviceResult {
  sent: number
  failed: number
  advice: string
}

function cloneItems(items: PlanItem[]): PlanItem[] {
  return items.map((i) => ({ ...i }))
}

export const usePlanStore = defineStore('plan', () => {
  const tripId = ref('')
  const days = ref<TripDay[]>([])
  const planned = ref<PlanItem[]>([])
  const unplanned = ref<PlanItem[]>([])
  const loading = ref(false)
  const error = ref('')

  /** 冲突列表（来自 GET /plan/conflicts），冲突标红只用这个集合。 */
  const conflicts = ref<PlanConflict[]>([])
  /** 命中冲突的条目 id 集合（前项与后项都标红，便于定位）。 */
  const conflictIds = computed<Set<string>>(() => {
    const ids = new Set<string>()
    for (const c of conflicts.value) {
      if (c.item_id) ids.add(c.item_id)
      if (c.with_item_id) ids.add(c.with_item_id)
    }
    return ids
  })
  /** 分类预设：先给本地兜底，接口成功再覆盖，下拉永远有值。 */
  const categories = ref<PlanCategory[]>([...DEFAULT_CATEGORIES])

  /** 自上次 flush() 以来是否有过写操作：页面据此决定离开时是否自动保存并提示。 */
  const dirty = ref(false)
  /** 尚未落库的写请求集合，flush() 会等待它们全部结束。 */
  const writes = new Set<Promise<unknown>>()

  /** 登记一个写请求：置脏 + 完成后移出集合，并在成功后刷新冲突。失败也移出，由调用方负责乐观回滚。 */
  function track<T>(p: Promise<T>): Promise<T> {
    dirty.value = true
    writes.add(p)
    void p.then(
      () => { writes.delete(p); void refreshConflicts() },
      () => { writes.delete(p) },
    )
    return p
  }

  /** 等待全部写请求落库并清除脏标记；等待期间新产生的写请求由下一轮循环覆盖。 */
  async function flush(): Promise<void> {
    while (writes.size) {
      await Promise.allSettled([...writes])
    }
    dirty.value = false
  }

  /** 全量条目：供地图 MapPane 与右栏「全部」筛选使用。 */
  const allItems = computed<PlanItem[]>(() =>
    sortByKey([...planned.value, ...unplanned.value]),
  )
  const plannedByDay = computed<Record<string, PlanItem[]>>(() => {
    const map: Record<string, PlanItem[]> = {}
    for (const day of days.value) map[day.id] = []
    for (const item of planned.value) {
      if (item.day_id) (map[item.day_id] ??= []).push(item)
    }
    for (const key of Object.keys(map)) map[key] = sortByKey(map[key])
    return map
  })

  function base(): string {
    return `/trips/${tripId.value}/plan`
  }

  /** 分类预设：接口不可用时静默保留本地 8 个中文预设，下拉不空白。 */
  async function loadCategories(): Promise<void> {
    try {
      const list = await api.get<PlanCategory[]>(`${base()}/categories`)
      if (Array.isArray(list) && list.length) {
        categories.value = list.map((c) => ({ id: String(c.id), label: String(c.label ?? c.id) }))
      }
    } catch {
      categories.value = [...DEFAULT_CATEGORIES]
    }
  }

  /**
   * 冲突检测：优先取后端 GET /plan/conflicts；接口不可用或返回异常时，
   * 用 lib/time.ts 的本地规则兜底（同一天、前项结束严格晚于后项开始才算冲突），
   * 保证卡片仍能即时标红，且与「14:00 结束 / 14:00 开始不冲突」的后端契约一致。
   */
  async function refreshConflicts(): Promise<void> {
    if (!tripId.value) return
    try {
      const list = await api.get<PlanConflict[]>(`${base()}/conflicts`)
      conflicts.value = Array.isArray(list) ? list : []
    } catch {
      const local = findLocalConflicts([...planned.value, ...unplanned.value])
      conflicts.value = local.map((c) => ({
        item_id: c.itemId,
        with_item_id: c.withItemId,
        start: '',
        end: '',
        reason: '时间冲突',
      }))
    }
  }

  /** 进入行程页：拉全量 plan，同时刷新冲突与分类预设（失败不阻断看板）。 */
  async function load(id: string): Promise<void> {
    tripId.value = id
    loading.value = true
    error.value = ''
    try {
      const data = await api.get<PlanData>(base())
      days.value = data.days ?? []
      planned.value = sortByKey(data.planned ?? [])
      unplanned.value = sortByKey(data.unplanned ?? [])
      void refreshConflicts()
      void loadCategories()
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      loading.value = false
    }
  }

  /** 智能重排某天时间：useAi=true 走 AI，后端失败会静默降级为按顺序重排。 */
  async function autoArrange(dayId: string, useAi = true): Promise<AutoArrangeResult> {
    return api.post<AutoArrangeResult>(`${base()}/auto-arrange`, { day_id: dayId, use_ai: useAi })
  }

  /** 天气与出行建议：生成建议并发送邮件，返回发送概况与建议正文。 */
  async function weatherAdvice(): Promise<WeatherAdviceResult> {
    return api.post<WeatherAdviceResult>(`/trips/${tripId.value}/weather-advice`)
  }

  async function addItem(payload: PlanItemCreate): Promise<PlanItem> {
    return track(api.post<PlanItem>(`${base()}/items`, payload))
  }

  /** 编辑条目：真实 PUT，返回服务端最新对象供本地合并。 */
  async function updateItem(itemId: string, patch: PlanItemPatch): Promise<PlanItem> {
    return track(api.put<PlanItem>(`${base()}/items/${itemId}`, patch))
  }

  async function deleteItem(itemId: string): Promise<void> {
    await track(api.del(`${base()}/items/${itemId}`))
  }

  async function importItems(items: PlanItemCreate[]): Promise<PlanItem[]> {
    const res = await track(api.post<{ created: number; items: PlanItem[] }>(`${base()}/import`, { items }))
    return res.items
  }

  /** 批量拖拽：一次性提交，后端单事务校验 before < new < after。 */
  async function move(moves: MoveIn[]): Promise<MoveResult> {
    return track(api.post<MoveResult>(`${base()}/moves`, { moves }))
  }

  /** 撤销最近一批（端点无 body，服务端按 batch 精确还原 before_*）。 */
  async function undo(): Promise<UndoResult> {
    return track(api.post<UndoResult>(`${base()}/moves/undo`))
  }

  async function addDay(payload: { date?: string | null; title?: string | null }): Promise<TripDay> {
    return track(api.post<TripDay>(`/trips/${tripId.value}/days`, payload))
  }

  /** 折叠 / 标题 / 天气等编辑，patch 使用 TripDayUpdate 允许的字段。 */
  async function updateDay(dayId: string, patch: Partial<Pick<TripDay, 'title' | 'note' | 'weather_json' | 'collapsed' | 'date' | 'day_index'>>): Promise<TripDay> {
    return track(api.put<TripDay>(`/trips/${tripId.value}/days/${dayId}`, patch))
  }

  // ---------------------------------------------------------------- 本地乐观操作
  function findItem(id: string): PlanItem | undefined {
    return planned.value.find((i) => i.id === id) ?? unplanned.value.find((i) => i.id === id)
  }

  function insertLocal(item: PlanItem): void {
    if (item.day_id === null) unplanned.value = sortByKey([...unplanned.value, item])
    else planned.value = sortByKey([...planned.value, item])
  }

  function removeLocal(id: string): void {
    planned.value = planned.value.filter((i) => i.id !== id)
    unplanned.value = unplanned.value.filter((i) => i.id !== id)
  }

  /** 用服务端返回对象替换本地条目（编辑成功后对齐）。 */
  function replaceLocal(item: PlanItem): void {
    const inPlanned = planned.value.some((i) => i.id === item.id)
    const inUnplanned = unplanned.value.some((i) => i.id === item.id)
    if (inPlanned || inUnplanned) {
      planned.value = planned.value.map((i) => (i.id === item.id ? item : i))
      unplanned.value = unplanned.value.map((i) => (i.id === item.id ? item : i))
    } else {
      insertLocal(item)
    }
    // day_id 可能因编辑改变，统一重新分组
    const all = [...planned.value, ...unplanned.value]
    planned.value = sortByKey(all.filter((i) => i.day_id !== null))
    unplanned.value = sortByKey(all.filter((i) => i.day_id === null))
  }

  /** 本地应用拖拽：改 day_id/bucket/sort_key 后按 day_id 重新分组（乐观更新）。 */
  function applyMovesLocal(moves: MoveIn[]): void {
    for (const m of moves) {
      const item = findItem(m.item_id)
      if (!item) continue
      item.day_id = m.to_day_id
      item.bucket = m.to_bucket
      item.sort_key = m.new_sort_key
    }
    const all = [...planned.value, ...unplanned.value]
    planned.value = sortByKey(all.filter((i) => i.day_id !== null))
    unplanned.value = sortByKey(all.filter((i) => i.day_id === null))
  }

  function snapshot(): PlanSnapshot {
    return { planned: cloneItems(planned.value), unplanned: cloneItems(unplanned.value) }
  }

  /** 失败回滚：恢复拖拽前的原数组。 */
  function restore(snap: PlanSnapshot): void {
    planned.value = cloneItems(snap.planned)
    unplanned.value = cloneItems(snap.unplanned)
  }

  return {
    tripId, days, planned, unplanned, loading, error, dirty,
    conflicts, conflictIds, categories,
    allItems, plannedByDay,
    load, flush,
    loadCategories, refreshConflicts, autoArrange, weatherAdvice,
    addItem, updateItem, deleteItem, importItems, move, undo, addDay, updateDay,
    findItem, insertLocal, removeLocal, replaceLocal, applyMovesLocal, snapshot, restore,
  }
})
