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

/** 后端业务错误码对应的中文提示，供 message 缺失时兜底。 */
export const ERROR_CODE_MESSAGES: Record<number, string> = {
  1002: '登录状态已失效，请重新登录',
  2001: '系统尚未完成安装，请先运行安装向导',
  2002: '系统已锁定，请先解锁',
  3002: '请先设置访问密码',
}

/** 把浏览器底层的英文网络异常转成中文。 */
function toChineseError(err: unknown): Error {
  if (err instanceof Error) {
    if (/failed to fetch|networkerror|load failed|network request failed/i.test(err.message)) {
      return new Error('网络连接失败，请检查网络后重试')
    }
    return err
  }
  return new Error('请求失败，请稍后重试')
}

/** 读取响应体：优先解析为对象，纯文本则原样返回，供错误文案提取。 */
async function readBody(resp: Response): Promise<Record<string, unknown> | string | null> {
  let raw = ''
  try {
    raw = await resp.text()
  } catch {
    return null
  }
  if (!raw.trim()) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : raw.trim()
  } catch {
    return raw.trim()
  }
}

/** 解析响应体里的中文错误；顺序：后端 message → 错误码提示 → detail → 中文兜底。 */
export async function readError(resp: Response): Promise<{ code: number; message: string; detail?: string }> {
  const fallback = `请求失败（状态码 ${resp.status}）`
  const body = await readBody(resp)
  if (!body) return { code: 5000, message: fallback }
  if (typeof body === 'string') {
    return { code: 5000, message: body.length <= 200 ? body : fallback }
  }
  const rawCode = Number(body.code)
  const code = Number.isFinite(rawCode) && body.code !== undefined ? rawCode : 5000
  const detail = typeof body.detail === 'string' ? body.detail : undefined
  let message = typeof body.message === 'string' ? body.message.trim() : ''
  if (!message && ERROR_CODE_MESSAGES[rawCode]) message = ERROR_CODE_MESSAGES[rawCode]
  if (!message && typeof body.detail === 'string') message = body.detail.trim()
  if (!message) message = fallback
  return { code, message, detail }
}

export async function request<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, { ...init, headers, credentials: 'same-origin' })
  } catch (err) {
    throw new ApiError(5000, toChineseError(err).message)
  }
  // 非 2xx：读取响应体 JSON 的 message，携错误码与中文文案抛出
  if (!resp.ok) {
    const e = await readError(resp)
    throw new ApiError(e.code, e.message, e.detail, resp.status)
  }
  let body: ApiEnvelope<T>
  try {
    body = (await resp.json()) as ApiEnvelope<T>
  } catch {
    throw new ApiError(5000, `响应解析失败（状态码 ${resp.status}）`, undefined, resp.status)
  }
  if (!resp.ok || body.code !== 0) {
    throw new ApiError(
      body.code ?? 5000,
      body.message || ERROR_CODE_MESSAGES[Number(body.code)] || `请求失败（状态码 ${resp.status}）`,
      body.detail,
      resp.status,
    )
  }
  return body.data
}

export const api = {
  get: <T = unknown>(path: string) => request<T>(path),
  post: <T = unknown>(path: string, data?: unknown) =>
    request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
  put: <T = unknown>(path: string, data?: unknown) =>
    request<T>(path, { method: 'PUT', body: data === undefined ? undefined : JSON.stringify(data) }),
  patch: <T = unknown>(path: string, data?: unknown) =>
    request<T>(path, { method: 'PATCH', body: data === undefined ? undefined : JSON.stringify(data) }),
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
      let resp: Response
      try {
        resp = await fetch(`${BASE}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
          body: JSON.stringify(body),
          credentials: 'same-origin',
          signal: controller.signal,
        })
      } catch (err) {
        throw toChineseError(err)
      }
      // 关键修复：非 2xx 时读取响应体 JSON 的 message，透出中文错误，不再吞掉响应体
      if (!resp.ok) {
        const e = await readError(resp)
        throw new ApiError(e.code, e.message, e.detail, resp.status)
      }
      // 少数配置错误会以 200 + JSON 包装返回，这里同样透出中文文案
      if ((resp.headers.get('content-type') ?? '').includes('application/json')) {
        const e = await readError(resp)
        if (e.code !== 0) throw new ApiError(e.code, e.message, e.detail, resp.status)
        handlers.onDone?.()
        return
      }
      if (!resp.body) throw new Error('流式连接未建立，请稍后重试')

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
      if ((err as Error).name !== 'AbortError') handlers.onError?.(toChineseError(err))
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
