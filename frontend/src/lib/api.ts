/** 统一 API 客户端：解包 {code,data,message,request_id}，支持 SSE 流式。 */
export interface ApiEnvelope<T> {
  code: number
  data: T
  message: string
  request_id: string
  detail?: string
}

export class ApiError extends Error {
  constructor(public code: number, message: string, public detail?: string, public status = 400) {
    super(message)
    this.name = 'ApiError'
  }
}

const BASE = '/api/v1'

export async function request<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const resp = await fetch(`${BASE}${path}`, { ...init, headers, credentials: 'same-origin' })
  let body: ApiEnvelope<T>
  try {
    body = (await resp.json()) as ApiEnvelope<T>
  } catch {
    throw new ApiError(5000, `响应不是 JSON (${resp.status})`, undefined, resp.status)
  }
  if (!resp.ok || body.code !== 0) {
    throw new ApiError(body.code ?? 5000, body.message || `请求失败 (${resp.status})`, body.detail, resp.status)
  }
  return body.data
}

export const api = {
  get: <T = unknown>(path: string) => request<T>(path),
  post: <T = unknown>(path: string, data?: unknown) =>
    request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
  put: <T = unknown>(path: string, data?: unknown) =>
    request<T>(path, { method: 'PUT', body: data === undefined ? undefined : JSON.stringify(data) }),
  del: <T = unknown>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T = unknown>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
}

export interface SSEHandlers {
  onEvent: (event: string, data: unknown) => void
  onError?: (error: Error) => void
  onDone?: () => void
}

/** POST + fetch stream 的 SSE（EventSource 不支持 POST body）。返回 AbortController 以停止。 */
export function postSSE(path: string, body: unknown, handlers: SSEHandlers): AbortController {
  const controller = new AbortController()
  ;(async () => {
    try {
      const resp = await fetch(`${BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify(body),
        credentials: 'same-origin',
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) throw new Error(`SSE 连接失败 (${resp.status})`)
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() ?? ''
        for (const chunk of chunks) {
          let event = 'message'
          let data = ''
          for (const line of chunk.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) data += line.slice(5).trim()
          }
          if (!data) continue
          try {
            handlers.onEvent(event, JSON.parse(data))
          } catch {
            handlers.onEvent(event, data)
          }
        }
      }
      handlers.onDone?.()
    } catch (err) {
      if ((err as Error).name !== 'AbortError') handlers.onError?.(err as Error)
    }
  })()
  return controller
}

/** GET 形式 SSE（协作事件广播），支持 Last-Event-ID 断线补发。 */
export function eventSource(path: string, onEvent: (event: string, data: unknown) => void): EventSource {
  const es = new EventSource(`${BASE}${path}`, { withCredentials: true })
  const relay = (ev: MessageEvent, name: string) => {
    try {
      onEvent(name, JSON.parse(ev.data))
    } catch {
      onEvent(name, ev.data)
    }
  }
  for (const name of ['delta', 'tool_call', 'tool_result', 'done', 'error', 'sync', 'ping']) {
    es.addEventListener(name, (ev) => relay(ev as MessageEvent, name))
  }
  return es
}
