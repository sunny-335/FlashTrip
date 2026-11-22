/** 行程导出：PDF 行程册与 ICS 日历。
 *  PDF / ICS 都是二进制或文本流，api.post 会 JSON 解析失败，故统一用原生 fetch + Blob。
 *  后端错误为统一 JSON 包装 {code,message,detail}，需识别后抛 ApiError 供调用方提示。
 *  另导出若干别名，兼容 PlanToolbar 通过 import.meta.glob 探测的函数名。
 */
import { ApiError } from '@/lib/api'

const BASE = '/api/v1'

interface ErrorEnvelope {
  code?: number
  message?: string
  detail?: string
}

/** 从 Content-Disposition 解析文件名，取不到时用兜底名。 */
function filenameOf(resp: Response, fallback: string): string {
  const raw = resp.headers.get('Content-Disposition') || ''
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(raw)
  if (match?.[1]) {
    try { return decodeURIComponent(match[1].replace(/"/g, '')) } catch { return match[1].replace(/"/g, '') }
  }
  return fallback
}

/** 触发浏览器下载并释放 ObjectURL。 */
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

/**
 * 统一的 fetch：非 2xx 或返回 JSON 错误包装时抛 ApiError；否则返回 Blob。
 * 后端异常处理器可能返回 4xx/5xx + JSON，也可能是 200 + code!=0 的包装。
 */
async function fetchBlob(path: string, init: RequestInit, fallbackName: string): Promise<void> {
  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, { ...init, credentials: 'same-origin' })
  } catch (e) {
    throw new ApiError(5000, `导出请求失败：${(e as Error)?.message || '网络异常'}`)
  }

  const type = resp.headers.get('Content-Type') || ''
  if (!resp.ok || type.includes('application/json') || type.includes('application/problem+json')) {
    let body: ErrorEnvelope = {}
    try { body = (await resp.json()) as ErrorEnvelope } catch { /* 非 JSON 错误体 */ }
    throw new ApiError(
      body.code ?? (resp.ok ? 5000 : resp.status),
      body.message || `导出失败 (${resp.status})`,
      body.detail,
      resp.status,
    )
  }

  const blob = await resp.blob()
  if (!blob.size) throw new ApiError(4001, '导出内容为空，请确认行程已包含数据')
  triggerDownload(blob, filenameOf(resp, fallbackName))
}

/** 导出 PDF 行程册（POST，StreamingResponse application/pdf）。 */
export async function downloadTripPdf(tripId: string): Promise<void> {
  if (!tripId) throw new ApiError(1001, '缺少行程 ID')
  await fetchBlob(`/trips/${encodeURIComponent(tripId)}/export/pdf`, { method: 'POST' }, 'flashtrip-trip.pdf')
}

/** 导出 ICS 日历（GET，scope = trip | all）。 */
export async function downloadIcs(tripId: string, scope: 'trip' | 'all' = 'trip'): Promise<void> {
  if (!tripId) throw new ApiError(1001, '缺少行程 ID')
  await fetchBlob(
    `/trips/${encodeURIComponent(tripId)}/export/ics?scope=${encodeURIComponent(scope)}`,
    { method: 'GET' },
    'flashtrip.ics',
  )
}

// PlanToolbar 用 glob 探测导出函数名，这里提供同义别名（均只需 tripId 一个参数）。
export const downloadPdf = downloadTripPdf
export const exportTripPdf = downloadTripPdf
export const exportPdf = downloadTripPdf
export const toPdf = downloadTripPdf
export const exportIcs = downloadIcs
export const exportICS = downloadIcs
export const exportTripIcs = downloadIcs
export const toIcs = downloadIcs
