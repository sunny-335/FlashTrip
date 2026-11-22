/** 行程列表 / 筛选 / 当前行程 / 概览。字段对齐 TripOut / TripCreate / overview。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/lib/api'

export type TripStatus = 'planned' | 'ongoing' | 'completed' | 'archived'
/** 对应 /trips?status= 的白名单；TopNavCenter 的 query.filter 也使用相同值。 */
export type TripFilter = 'all' | 'active' | 'completed'

export interface Trip {
  id: string
  owner_id: string
  title: string
  destination: string | null
  start_date: string | null
  end_date: string | null
  cover_url: string | null
  status: string
  timezone: string
  currency: string
  visibility: string
  created_at: string | null
  updated_at: string | null
}

export interface TripCreate {
  title: string
  destination?: string | null
  start_date?: string | null
  end_date?: string | null
  cover_url?: string | null
  status?: TripStatus
  timezone?: string
  currency?: string
  visibility?: string
}

export interface TripOverview {
  trip: Trip
  days_count: number
  item_count: number
  planned_count: number
  unplanned_count: number
  geocoded_count: number
}

const LS_KEY = 'flashtrip.currentTripId'

function readCurrent(): string | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage.getItem(LS_KEY) : null
  } catch {
    return null
  }
}

export function normalizeFilter(v: unknown): TripFilter {
  return v === 'active' || v === 'completed' ? v : 'all'
}

export const useTripStore = defineStore('trip', () => {
  const trips = ref<Trip[]>([])
  const filter = ref<TripFilter>('all')
  const currentTripId = ref<string | null>(readCurrent())
  const loading = ref(false)
  const error = ref('')

  const currentTrip = computed(() => trips.value.find((t) => t.id === currentTripId.value) ?? null)

  async function load(nextFilter?: TripFilter): Promise<void> {
    if (nextFilter) filter.value = nextFilter
    loading.value = true
    error.value = ''
    try {
      trips.value = await api.get<Trip[]>(`/trips?status=${filter.value}`)
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function create(payload: TripCreate): Promise<Trip> {
    const t = await api.post<Trip>('/trips', payload)
    trips.value.push(t)
    return t
  }

  /** 「设置当前行程」：PUT /trips/{id}/current，并本地持久化便于仪表盘首选。 */
  async function setCurrent(id: string): Promise<void> {
    await api.put(`/trips/${id}/current`)
    currentTripId.value = id
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(LS_KEY, id)
    } catch {
      /* 隐私模式下忽略 */
    }
  }

  async function overview(id: string): Promise<TripOverview> {
    return api.get<TripOverview>(`/trips/${id}/overview`)
  }

  return {
    trips, filter, currentTripId, currentTrip, loading, error,
    load, create, setCurrent, overview,
  }
})
