/** 行程导出：PDF 行程册与 ICS 日历。
 *  PDF / ICS 是二进制或文本流，普通 api.get/post 会按 JSON 解析导致失败，
 *  因此这里仍基于统一的 API 前缀发起原生请求，并用 ApiError 透出中文错误。
 *  另导出若干别名，兼容 PlanToolbar 通过 import.meta.glob 探测的函数名。
 */
import { ApiError, readError } from '@/lib/api'

const BASE = '/api/v1'

/** 判断响应是否是后端统一 JSON 包装或错误信息。 */
function isJsonResponse(type: string): boolean {
  return /(?:application|text)\/(?:[\w.-]*\+)?json|application\/problem\+json/i.test(type)
}

/** 从 Content-Disposition 解析文件名，兼容普通 filename 与 UTF-8 filename*。 */
function filenameOf(resp: Response, fallback: string): string {
  const raw = resp.headers.get('Content-Disposition') || ''
  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(raw)
  const plain = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(raw)
  let name = encoded?.[1] || plain?.[1] || plain?.[2] || ''
  if (!name.trim()) return fallback
  name = name.trim().replace(/^"|"$/g, '')
  try { name = decodeURIComponent(name) } catch { /* 文件名不是百分号编码时保持原值 */ }
  // 只保留文件名主体，避免下载属性中出现路径或换行控制字符
  name = name.split(/[\\/]/).pop()?.replace(/[\r\n\t]/g, '').trim() || ''
  return name || fallback
}

/** 触发浏览器下载并在稍后释放 ObjectURL。 */
function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 稍后释放，避免部分浏览器尚未发起下载
  window.setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/** 统一读取文件流：错误转成 ApiError，成功按响应类型创建 Blob 并下载。 */
async function fetchBlob(path: string, init: RequestInit, fallbackName: string): Promise<void> {
  let resp: Response
  try {
    const headers = new Headers(init.headers)
    headers.set('Accept', init.method === 'POST'
      ? 'application/pdf, application/json;q=0.9, */*;q=0.1'
      : 'text/calendar, application/json;q=0.9, */*;q=0.1')
    resp = await fetch(`${BASE}${path}`, { ...init, headers, credentials: 'same-origin' })
  } catch (err) {
    throw new ApiError(5000, `导出请求失败：${(err as Error)?.message || '网络异常'}`)
  }

  const type = resp.headers.get('Content-Type') || ''
  const jsonLike = isJsonResponse(type)

  // 非 2xx：优先读取后端统一错误包装；二进制错误体不展示乱码
  if (!resp.ok) {
    const info = jsonLike ? await readError(resp.clone()) : null
    throw new ApiError(
      info?.code ?? resp.status,
      info?.message || `导出失败（状态码 ${resp.status}）`,
      info?.detail,
      resp.status,
    )
  }

  // 200 但返回 JSON：不是文件流；若 code != 0，则透出后端中文提示
  if (jsonLike) {
    const info = await readError(resp.clone())
    const code = info.code || 5000
    throw new ApiError(
      info.code === 0 ? 4001 : code,
      info.code === 0 ? '导出接口返回了非文件内容，请稍后重试' : info.message,
      info.detail,
      resp.status,
    )
  }

  let buffer: ArrayBuffer
  try {
    buffer = await resp.arrayBuffer()
  } catch (err) {
    throw new ApiError(5000, `导出内容读取失败：${(err as Error)?.message || '网络异常'}`)
  }
  const blob = new Blob([buffer], { type: type || 'application/octet-stream' })
  if (!blob.size) throw new ApiError(4001, '导出内容为空，请确认行程已包含数据')
  triggerDownload(blob, filenameOf(resp, fallbackName))
}

/** 导出 PDF 行程册（POST，返回 application/pdf 文件流）。 */
export async function downloadTripPdf(tripId: string): Promise<void> {
  if (!tripId) throw new ApiError(1001, '缺少行程 ID')
  await fetchBlob(`/trips/${encodeURIComponent(tripId)}/export/pdf`, { method: 'POST' }, 'flashtrip-trip.pdf')
}

/** 导出 ICS 日历（GET，scope = trip | all）。 */
export async function downloadIcs(tripId: string, scope: 'trip' | 'all' = 'trip'): Promise<void> {
  if (!tripId) throw new ApiError(1001, '缺少行程 ID')
  const safeScope = scope === 'all' ? 'all' : 'trip'
  await fetchBlob(
    `/trips/${encodeURIComponent(tripId)}/export/ics?scope=${encodeURIComponent(safeScope)}`,
    { method: 'GET' },
    'flashtrip.ics',
  )
}

// PlanToolbar 用 glob 探测导出函数名，这里提供同义别名（均只需 tripId 一个参数）。
export const downloadPdf = downloadTripPdf
export const exportTripPdf = downloadTripPdf
export const exportPdf = downloadTripPdf
export const toPdf = downloadTripPdf
export const pdf = downloadTripPdf
export const exportIcs = downloadIcs
export const downloadIcsAlias = downloadIcs
export const exportICS = downloadIcs
export const exportTripIcs = downloadIcs
export const toIcs = downloadIcs
export const ics = downloadIcs
