/** 协作事件同步：SSE 主通道 + 断线轮询降级。
 *
 *  后端 /trips/{id}/events 的 event 名是动态的（booking.created / moment.created …），
 *  而 api.eventSource 只注册了固定名，故这里在返回的 EventSource 上补注册全部业务事件名。
 *  断线（onerror）时改用 GET /trips/{id}/events/since?cursor= 轮询补发，
 *  恢复（onopen）后停止轮询并做一次增量对齐。游标取自事件里的自增 id（Last-Event-ID）。
 */
import { getCurrentInstance, onBeforeUnmount, ref, type Ref } from 'vue'
import { api, eventSource } from '@/lib/api'

export interface SyncEvent {
  id?: number
  trip_id?: string
  event_type: string
  payload?: Record<string, unknown>
  actor_id?: string | null
  created_at?: string
}

/** 后端 emit() 使用过的事件名全集；EventSource 需逐个 addEventListener。 */
export const SYNC_EVENT_NAMES: string[] = [
  'booking.created', 'booking.updated', 'booking.deleted',
  'transport.created', 'transport.updated', 'transport.deleted',
  'expense.created', 'expense.updated', 'expense.deleted',
  'packing.list_created', 'packing.list_updated', 'packing.list_deleted',
  'packing.item_created', 'packing.item_updated', 'packing.item_deleted',
  'moment.created', 'moment.updated', 'moment.deleted',
  'member.permissions_updated', 'member.removed',
  'attachment.created',
  'plan.item_created', 'plan.item_updated', 'plan.item_deleted', 'plan.moved', 'plan.undone',
  'trip.updated',
]

export interface UseSSEOptions {
  onEvent: (ev: SyncEvent) => void
  pollIntervalMs?: number
}

export interface UseSSEApi {
  connected: Ref<boolean>
  mode: Ref<'sse' | 'poll' | 'off'>
  cursor: Ref<number>
  error: Ref<string>
  start: () => void
  stop: () => void
  pollNow: () => Promise<void>
}

function toEvent(name: string, raw: unknown): SyncEvent | null {
  let data: Record<string, unknown> | null = null
  if (raw && typeof raw === 'object') data = raw as Record<string, unknown>
  else if (typeof raw === 'string') {
    try { data = JSON.parse(raw) as Record<string, unknown> } catch { return null }
  }
  if (!data) return null
  return {
    id: typeof data.id === 'number' ? data.id : undefined,
    trip_id: typeof data.trip_id === 'string' ? data.trip_id : undefined,
    event_type: String(data.event_type || name || 'sync'),
    payload: (data.payload && typeof data.payload === 'object')
      ? data.payload as Record<string, unknown> : {},
    actor_id: typeof data.actor_id === 'string' ? data.actor_id : null,
    created_at: typeof data.created_at === 'string' ? data.created_at : undefined,
  }
}

export function useSSE(
  tripId: string | (() => string),
  options: UseSSEOptions,
): UseSSEApi {
  const connected = ref(false)
  const mode = ref<'sse' | 'poll' | 'off'>('off')
  const cursor = ref(0)
  const error = ref('')

  let es: EventSource | null = null
  let timer: number | null = null
  let polling = false
  let stopped = true

  const resolveId = () => encodeURIComponent(typeof tripId === 'function' ? tripId() : tripId)
  const interval = options.pollIntervalMs ?? 3000

  function deliver(name: string, raw: unknown): void {
    const ev = toEvent(name, raw)
    if (!ev) return
    if (typeof ev.id === 'number' && ev.id > cursor.value) cursor.value = ev.id
    options.onEvent(ev)
  }

  /** 增量补发；后端返回的 cursor 是「请求时的游标」，需用事件 id 自行推进。 */
  async function pollNow(): Promise<void> {
    if (stopped || polling) return
    const id = resolveId()
    if (!id) return
    polling = true
    try {
      const res = await api.get<{ events?: SyncEvent[]; cursor?: number }>(
        `/trips/${id}/events/since?cursor=${cursor.value}`,
      )
      for (const raw of res.events ?? []) {
        const ev = toEvent(raw.event_type, raw)
        if (!ev) continue
        if (typeof ev.id === 'number' && ev.id > cursor.value) cursor.value = ev.id
        options.onEvent(ev)
      }
      error.value = ''
    } catch (e) {
      error.value = (e as Error)?.message || '增量同步失败'
    } finally {
      polling = false
    }
  }

  function startPolling(): void {
    if (timer !== null) return
    mode.value = 'poll'
    void pollNow()
    timer = window.setInterval(() => { void pollNow() }, interval)
  }

  function stopPolling(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function start(): void {
    stop()
    stopped = false
    const id = resolveId()
    if (!id) return
    mode.value = 'sse'
    try {
      es = eventSource(`/trips/${id}/events`, (name, data) => deliver(name, data))
      for (const name of SYNC_EVENT_NAMES) {
        es.addEventListener(name, (e) => deliver(name, (e as MessageEvent).data))
      }
      es.onopen = () => {
        connected.value = true
        mode.value = 'sse'
        error.value = ''
        stopPolling()
        void pollNow() // 补上断线期间可能遗漏的事件
      }
      es.onerror = () => {
        connected.value = false
        // EventSource 会自动重连；期间用轮询保证不丢事件
        startPolling()
      }
      void pollNow() // 首屏历史事件对齐
    } catch (e) {
      connected.value = false
      error.value = (e as Error)?.message || 'SSE 连接失败'
      startPolling()
    }
  }

  function stop(): void {
    stopped = true
    stopPolling()
    if (es) {
      es.onopen = null
      es.onerror = null
      es.close()
      es = null
    }
    connected.value = false
    mode.value = 'off'
  }

  // 在组件内调用时自动清理；在 store 中调用则交由 store.disconnect() 管理
  if (getCurrentInstance()) onBeforeUnmount(stop)

  return { connected, mode, cursor, error, start, stop, pollNow }
}
