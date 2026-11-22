/** Agent 会话状态：对话历史、流式缓冲、工具调用与二次确认。
 *  /ai/chat 为 SSE（delta / tool_call / tool_result / done / error）；
 *  写类工具 needConfirm=true，必须由 ToolCallCard 确认后以 confirmToolCalls 回传才会执行。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, postSSE, ApiError } from '@/lib/api'

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

  /** 发起一轮对话（或确认后回传）。body 的 messages / context 对齐后端 _ensure_conversation。 */
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
    start({
      messages: wireMessages(),
      conversation_id: conversationId.value || undefined,
      context,
      ...context,
    })
  }

  /** 用户点「确认」：把写工具以 confirmToolCalls 回传 /ai/chat，后端走同一套权限校验执行。 */
  function confirm(calls: ToolCall[], context: Record<string, unknown>): void {
    if (!calls.length || streaming.value) return
    for (const c of calls) c.status = 'running'
    pendingCalls.value = []
    start({
      messages: wireMessages(),
      conversation_id: conversationId.value || undefined,
      confirmToolCalls: calls.map((c) => ({
        toolCallId: c.toolCallId,
        name: c.name,
        arguments: c.arguments,
      })),
      context,
      ...context,
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

  async function loadConversations(): Promise<unknown[]> {
    try { return await api.get<unknown[]>('/ai/conversations') } catch (e) {
      if (e instanceof ApiError) error.value = e.message
      return []
    }
  }

  return {
    conversationId, messages, pendingCalls, streaming, streamBuffer, error,
    send, confirm, cancel, stop, reset, loadConversations,
  }
})
