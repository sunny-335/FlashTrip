/** Agent 会话状态：会话列表、对话历史、流式缓冲、工具调用与二次确认。
 *  /ai/chat 为 SSE（delta / tool_call / tool_result / done / error）；
 *  写类工具 needConfirm=true，必须由 ToolCallCard 确认后以 confirmToolCalls 回传才会执行。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, postSSE, ApiError } from '@/lib/api'

/** 工具中文标签：面板清单与工具卡片共用，避免直接把英文工具名暴露给用户。 */
export const TOOL_LABELS: Record<string, string> = {
  list_trips: '列出行程',
  get_plan: '读取行程安排',
  get_expenses: '读取费用',
  search_poi: '搜索地点',
  get_bookings: '读取预订',
  get_transports: '读取交通',
  get_packing: '读取行李清单',
  get_moments: '读取旅途瞬间',
  get_shares: '读取分享链接',
  get_weather: '查询天气',
  add_plan_item: '新增行程条目',
  move_plan_item: '移动行程条目',
  create_booking: '新增预订',
  delete_trip: '删除行程',
  rearrange_plan_times: '重排计划时间',
  set_moment_public: '设置瞬间公开',
  create_expense: '新增费用',
}

/** 取工具中文标签；后端新增工具时回退原名，不影响展示。 */
export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

export type ToolCallStatus = 'running' | 'pending' | 'done' | 'cancelled' | 'error'

export interface ToolCall {
  toolCallId: string
  name: string
  arguments: Record<string, unknown>
  needConfirm: boolean
  permission?: string | null
  message?: string
  status: ToolCallStatus
  result?: unknown
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  streaming?: boolean
  toolCalls?: ToolCall[]
}

export interface ConversationItem {
  id: string
  title?: string
  scope?: string
  created_at?: string
  updated_at?: string
}

interface DeltaData { delta?: string; content?: string; notice?: string }
interface ToolCallData {
  toolCallId?: string
  name?: string
  arguments?: Record<string, unknown> | string
  needConfirm?: boolean
  permission?: string | null
  message?: string
  confirmed?: boolean
}
interface ToolResultData { toolCallId?: string; name?: string; result?: unknown }
interface DoneData {
  conversationId?: string
  pendingConfirmation?: boolean
  toolCalls?: { toolCallId: string; name: string; arguments: Record<string, unknown> }[]
}
interface ErrorData { code?: number; message?: string }
interface HistoryRow { id?: string; role?: string; content?: string; toolCalls?: { toolCallId?: string; name?: string; arguments?: Record<string, unknown> }[]; tool_calls_json?: string; toolCallId?: string; tool_call_id?: string; toolResult?: unknown }

let seq = 0
function nextId(): string { return `m${Date.now().toString(36)}-${(seq++).toString(36)}` }

function parseArgs(raw: ToolCallData['arguments']): Record<string, unknown> {
  if (raw && typeof raw === 'object') return raw
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) as Record<string, unknown> } catch { return {} }
  }
  return {}
}

export const useAgentStore = defineStore('agent', () => {
  const conversationId = ref('')
  const conversations = ref<ConversationItem[]>([])
  const provider = ref('')
  const model = ref('')
  const messages = ref<ChatMessage[]>([])
  const pendingCalls = ref<ToolCall[]>([])
  const streaming = ref(false)
  const streamBuffer = ref('')
  const error = ref('')
  let controller: AbortController | null = null

  /** 供后端 _messages() 使用：只取 role/content，去掉本地展示字段。 */
  function wireMessages(): { role: string; content: string }[] {
    return messages.value
      .filter((m) => m.role !== 'tool' && (m.content || m.streaming))
      .map((m) => ({ role: m.role, content: m.content }))
  }

  function pushAssistant(): ChatMessage {
    const last = messages.value[messages.value.length - 1]
    if (last?.role === 'assistant' && last.streaming) return last
    const msg: ChatMessage = { id: nextId(), role: 'assistant', content: '', streaming: true, toolCalls: [] }
    messages.value.push(msg)
    return msg
  }

  function finishStream(): void {
    for (const m of messages.value) if (m.streaming) m.streaming = false
    streaming.value = false
  }

  function allToolCalls(): ToolCall[] {
    return messages.value.flatMap((m) => m.toolCalls ?? [])
  }

  function upsertCall(data: ToolCallData, status: ToolCallStatus): ToolCall | null {
    const id = data.toolCallId || nextId()
    const existing = allToolCalls().find((c) => c.toolCallId === id)
    if (existing) {
      existing.status = status
      if (data.needConfirm !== undefined) existing.needConfirm = data.needConfirm
      if (data.permission) existing.permission = data.permission
      if (data.message) existing.message = data.message
      return existing
    }
    const msg = pushAssistant()
    const call: ToolCall = {
      toolCallId: id,
      name: data.name || 'tool',
      arguments: parseArgs(data.arguments),
      needConfirm: Boolean(data.needConfirm),
      permission: data.permission ?? null,
      message: data.message,
      status,
    }
    msg.toolCalls = [...(msg.toolCalls ?? []), call]
    return call
  }

  function handleEvent(event: string, data: unknown): void {
    const d = (data ?? {}) as Record<string, unknown>
    switch (event) {
      case 'delta': {
        const dd = d as DeltaData
        const chunk = dd.delta ?? dd.content ?? ''
        if (chunk) {
          streamBuffer.value += chunk
          pushAssistant().content = streamBuffer.value
        }
        if (dd.notice) {
          streamBuffer.value += `\n${dd.notice}\n`
          pushAssistant().content = streamBuffer.value
        }
        break
      }
      case 'tool_call': {
        const td = d as ToolCallData
        const status: ToolCallStatus = td.needConfirm ? 'pending' : 'running'
        const call = upsertCall(td, status)
        if (call && td.needConfirm && !pendingCalls.value.some((c) => c.toolCallId === call.toolCallId)) {
          pendingCalls.value.push(call)
        }
        break
      }
      case 'tool_result': {
        const tr = d as ToolResultData
        const call = allToolCalls().find((c) => c.toolCallId === tr.toolCallId)
        if (call) { call.result = tr.result; call.status = 'done' }
        break
      }
      case 'done': {
        const dn = d as DoneData
        if (dn.conversationId) conversationId.value = dn.conversationId
        if (dn.pendingConfirmation && Array.isArray(dn.toolCalls)) {
          for (const raw of dn.toolCalls) {
            const call = allToolCalls().find((c) => c.toolCallId === raw.toolCallId)
            if (call) {
              call.status = 'pending'
              call.arguments = raw.arguments ?? call.arguments
              call.name = raw.name || call.name
              if (!pendingCalls.value.some((c) => c.toolCallId === call.toolCallId)) pendingCalls.value.push(call)
            }
          }
        }
        break
      }
      case 'error': {
        const ed = d as ErrorData
        error.value = ed.message || '对话生成失败'
        streamBuffer.value += `\n[错误] ${error.value}\n`
        pushAssistant().content = streamBuffer.value
        break
      }
      default:
        break
    }
  }

  /** 组装 /ai/chat 请求体公共字段：对话 + 会话 + 页面上下文 + 动态模型。 */
  function baseBody(context: Record<string, unknown>): Record<string, unknown> {
    return {
      messages: wireMessages(),
      conversation_id: conversationId.value || undefined,
      context,
      ...context,
      ...(provider.value ? { provider: provider.value } : {}),
      ...(model.value ? { model: model.value } : {}),
    }
  }

  /** 发起一轮对话（或确认后回传）。 */
  function start(body: Record<string, unknown>): void {
    controller?.abort()
    streaming.value = true
    streamBuffer.value = ''
    error.value = ''
    controller = postSSE('/ai/chat', body, {
      onEvent: handleEvent,
      onError: (e) => { error.value = e.message; finishStream() },
      onDone: () => finishStream(),
    })
  }

  function send(text: string, context: Record<string, unknown>): void {
    const content = text.trim()
    if (!content || streaming.value) return
    messages.value.push({ id: nextId(), role: 'user', content })
    start(baseBody(context))
  }

  /** 用户点「确认」：把写工具以 confirmToolCalls 回传 /ai/chat，后端走同一套权限校验执行。 */
  function confirm(calls: ToolCall[], context: Record<string, unknown>): void {
    if (!calls.length || streaming.value) return
    for (const c of calls) c.status = 'running'
    pendingCalls.value = []
    start({
      ...baseBody(context),
      confirmToolCalls: calls.map((c) => ({
        toolCallId: c.toolCallId,
        name: c.name,
        // 删除行程是危险操作，必须回传 confirm:"yes" 后端才会执行
        arguments: c.name === 'delete_trip' ? { ...c.arguments, confirm: 'yes' } : c.arguments,
      })),
    })
  }

  /** 用户点「取消」：仅前端丢弃，不向后端发送任何写工具。 */
  function cancel(calls: ToolCall[]): void {
    for (const c of calls) c.status = 'cancelled'
    pendingCalls.value = []
  }

  async function stop(): Promise<void> {
    controller?.abort()
    controller = null
    finishStream()
    if (conversationId.value) {
      try { await api.post(`/ai/chat/${encodeURIComponent(conversationId.value)}/stop`) } catch { /* 忽略 */ }
    }
  }

  function reset(): void {
    controller?.abort()
    controller = null
    conversationId.value = ''
    messages.value = []
    pendingCalls.value = []
    streamBuffer.value = ''
    error.value = ''
    streaming.value = false
  }

  /** 设置本轮对话使用的供应商与模型（来自动态 /ai/models，不硬编码）。 */
  function setModel(nextProvider: string, nextModel: string): void {
    provider.value = nextProvider
    model.value = nextModel
  }

  /** 拉取历史会话列表。 */
  async function loadConversations(): Promise<ConversationItem[]> {
    try {
      conversations.value = await api.get<ConversationItem[]>('/ai/conversations')
    } catch (e) {
      if (e instanceof ApiError) error.value = e.message
      conversations.value = []
    }
    return conversations.value
  }

  /** 切换会话：加载该会话的历史消息并复用其 conversationId。 */
  async function renameConversation(id: string, title: string): Promise<void> {
    const updated = await api.patch<ConversationItem>(`/ai/conversations/${encodeURIComponent(id)}`, { title })
    conversations.value = conversations.value.map((item) => item.id === id ? { ...item, ...updated } : item)
  }

  async function deleteConversation(id: string): Promise<void> {
    await api.del(`/ai/conversations/${encodeURIComponent(id)}`)
    conversations.value = conversations.value.filter((item) => item.id !== id)
    if (conversationId.value === id) reset()
  }

  async function openConversation(id: string): Promise<void> {
    controller?.abort()
    controller = null
    streaming.value = false
    streamBuffer.value = ''
    try {
      const rows = await api.get<HistoryRow[]>(`/ai/conversations/${encodeURIComponent(id)}/messages`)
      conversationId.value = id
      messages.value = rows.map((row, index) => {
        let rawCalls = row.toolCalls
        if (!rawCalls && row.tool_calls_json) {
          try { rawCalls = JSON.parse(row.tool_calls_json) as HistoryRow['toolCalls'] } catch { rawCalls = [] }
        }
        const toolCalls: ToolCall[] = (rawCalls ?? []).map((call, n) => ({
          toolCallId: call.toolCallId || `h${index}-t${n}`,
          name: call.name || 'tool', arguments: call.arguments ?? {}, needConfirm: false, status: 'done',
        }))
        if (row.role === 'tool' && row.toolCallId) {
          const call = messages.value.flatMap((m) => m.toolCalls ?? []).find((item) => item.toolCallId === row.toolCallId)
          if (call) { call.result = row.toolResult ?? row.content; call.status = 'done' }
        }
        return {
          id: row.id || `h${index}`,
          role: row.role === 'user' ? 'user' as const : row.role === 'tool' ? 'tool' as const : 'assistant' as const,
          content: row.content ?? '', toolCalls,
        }
      })
      pendingCalls.value = []
      error.value = ''
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '会话消息加载失败，请稍后重试'
    }
  }

  /** 新建会话：清空当前对话，保留已选模型偏好。 */
  function newConversation(): void {
    reset()
  }

  return {
    conversationId, conversations, provider, model,
    messages, pendingCalls, streaming, streamBuffer, error,
    send, confirm, cancel, stop, reset, setModel,
    loadConversations, openConversation, renameConversation, deleteConversation, newConversation,
  }
})
