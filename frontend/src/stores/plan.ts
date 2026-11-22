/** 三栏计划板数据 + API。字段严格对齐 schemas/plan.py 与 TripDayOut。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/lib/api'
import { sortByKey } from '@/lib/sortKey'

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

  /** 全量条目：供地图 MapPane 与右栏「All」筛选使用。 */
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

  async function load(id: string): Promise<void> {
    tripId.value = id
    loading.value = true
    error.value = ''
    try {
      const data = await api.get<PlanData>(base())
      days.value = data.days ?? []
      planned.value = sortByKey(data.planned ?? [])
      unplanned.value = sortByKey(data.unplanned ?? [])
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function addItem(payload: PlanItemCreate): Promise<PlanItem> {
    return api.post<PlanItem>(`${base()}/items`, payload)
  }

  async function deleteItem(itemId: string): Promise<void> {
    await api.del(`${base()}/items/${itemId}`)
  }

  async function importItems(items: PlanItemCreate[]): Promise<PlanItem[]> {
    const res = await api.post<{ created: number; items: PlanItem[] }>(`${base()}/import`, { items })
    return res.items
  }

  /** 批量拖拽：一次性提交，后端单事务校验 before < new < after。 */
  async function move(moves: MoveIn[]): Promise<MoveResult> {
    return api.post<MoveResult>(`${base()}/moves`, { moves })
  }

  /** 撤销最近一批（端点无 body，服务端按 batch 精确还原 before_*）。 */
  async function undo(): Promise<UndoResult> {
    return api.post<UndoResult>(`${base()}/moves/undo`)
  }

  async function addDay(payload: { date?: string | null; title?: string | null }): Promise<TripDay> {
    return api.post<TripDay>(`/trips/${tripId.value}/days`, payload)
  }

  /** 折叠 / 标题 / 天气等编辑，patch 使用 TripDayUpdate 允许的字段。 */
  async function updateDay(dayId: string, patch: Partial<Pick<TripDay, 'title' | 'note' | 'weather_json' | 'collapsed' | 'date' | 'day_index'>>): Promise<TripDay> {
    return api.put<TripDay>(`/trips/${tripId.value}/days/${dayId}`, patch)
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
    tripId, days, planned, unplanned, loading, error, allItems, plannedByDay,
    load, addItem, deleteItem, importItems, move, undo, addDay, updateDay,
    findItem, insertLocal, removeLocal, applyMovesLocal, snapshot, restore,
  }
})
