/** Agent 上下文：从当前路由 + 当前行程组装 {scope, tab, path, trip_id, summary}。
 *  tab 必传，后端据此注入 system 页面提示；selection 由各页面通过 setAgentSelection 写入。
 */
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTripStore } from '@/stores/trip'
import { usePlanStore } from '@/stores/plan'

/** 用类型别名而非接口，便于直接作为页面上下文对象透传给请求体。 */
export type AgentContext = {
  scope: string
  trip_id: string | null
  tab: string
  path: string
  selection: Record<string, unknown> | null
  summary: string
}

const selection = ref<Record<string, unknown> | null>(null)

export function setAgentSelection(value: Record<string, unknown> | null): void {
  selection.value = value
}

export function useAgentContext() {
  const route = useRoute()
  const trips = useTripStore()
  const plan = usePlanStore()

  const scope = computed<string>(() => {
    const name = String(route.name ?? '')
    if (name === 'trip-plan') return 'plan'
    if (name.startsWith('trip-')) return 'trip'
    return 'global'
  })

  const tripId = computed<string | null>(() => {
    const raw = route.params.tripId
    return typeof raw === 'string' && raw ? raw : null
  })

  /** tab 取路由名，缺省时以路径兜底，保证后端一定能注入页面上下文提示。 */
  const tab = computed<string>(() =>
    String(route.name ?? '') || route.path.replace(/^\//, '').replace(/\//g, '-') || 'global',
  )

  const summary = computed<string>(() => {
    const id = tripId.value
    const trip = (id ? trips.trips.find((t) => t.id === id) : null) ?? trips.currentTrip
    if (!trip) return selection.value ? `当前选中：${JSON.stringify(selection.value)}` : ''
    const parts = [trip.title]
    if (trip.destination) parts.push(trip.destination)
    if (id && plan.tripId === id) {
      parts.push(`${plan.days.length} 天 / ${plan.allItems.length} 个条目`)
    }
    if (selection.value) parts.push(`选中：${JSON.stringify(selection.value)}`)
    return parts.join(' · ')
  })

  const context = computed<AgentContext>(() => ({
    scope: scope.value,
    trip_id: tripId.value,
    tab: tab.value,
    path: route.fullPath,
    selection: selection.value,
    summary: summary.value,
  }))

  /** 组装 /ai/chat 请求体：messages 为后端识别的对话字段，context 为页面上下文快照。 */
  function buildChatBody(messages: unknown[], extra: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      messages,
      ...context.value,
      context: context.value,
      ...extra,
    }
  }

  return { context, scope, tripId, tab, summary, buildChatBody, setAgentSelection }
}
