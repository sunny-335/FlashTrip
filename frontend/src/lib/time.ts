/** 行程时间工具：时长格式化 / 解析、HH:mm 与分钟互转、ISO 拼接、本地冲突判定。
 *  - 时长在界面统一显示为 2h10m（用户明确要求），输入兼容「2小时10分钟」「130」「2h10m」「1:30」；
 *  - 冲突规则与后端 /plan/conflicts 一致：同一行程日内，只有「前项结束 > 后项开始」才算冲突，
 *    前项 14:00 结束、后项 14:00 开始首尾相接不算冲突。
 */

/** 分钟 → 时长记号：0→0m、60→1h、130→2h10m、1440→24h。 */
export function formatDuration(min: number | null | undefined): string {
  const total = Math.max(0, Math.round(Number(min) || 0))
  const h = Math.floor(total / 60)
  const m = total % 60
  if (h > 0 && m > 0) return `${h}h${m}m`
  if (h > 0) return `${h}h`
  return `${m}m`
}

/** 解析时长输入，统一返回分钟数；无法识别返回 null。
 *  支持：2小时10分钟 / 2时10分 / 2h10m / 130（纯分钟） / 1:30 / 90m / 1h30 / 1.5h。
 */
export function parseDuration(input: string | number | null | undefined): number | null {
  if (input === null || input === undefined) return null
  const raw = String(input).trim()
  if (!raw) return null

  // 时:分（1:30、01:30）单独处理，避免与纯分钟数混淆
  const colon = /^(\d{1,2}):(\d{1,2})$/.exec(raw)
  if (colon) return Number(colon[1]) * 60 + Number(colon[2])

  // 中文单位与记号归一化：小时/时→h，分钟/分→m，去空格、转小写
  const token = raw
    .replace(/\s+/g, '')
    .replace(/小时|时/g, 'h')
    .replace(/分钟|分/g, 'm')
    .toLowerCase()
  // 记号形如 2h10m / 90m / 1h / 1h30；纯数字 130 按「分钟」解释
  const m2 = /^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m?)?$/.exec(token)
  if (!m2 || (!m2[1] && !m2[2])) return null
  const hours = m2[1] ? Number(m2[1]) : 0
  const mins = m2[2] ? Number(m2[2]) : 0
  const total = Math.round(hours * 60 + mins)
  return Number.isFinite(total) && total >= 0 ? total : null
}

/** 'HH:mm' → 当天分钟数（0..1439）；格式非法返回 NaN。 */
export function toMinutes(hhmm: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec((hhmm || '').trim())
  if (!m) return NaN
  const h = Number(m[1])
  const min = Number(m[2])
  if (h > 23 || min > 59) return NaN
  return h * 60 + min
}

/** 分钟数 → 'HH:mm'；超过一天自动取模（跨天结束显示为次日钟点）。 */
export function minutesToClock(min: number): string {
  const total = ((Math.round(min) % 1440) + 1440) % 1440
  const h = Math.floor(total / 60)
  const m = total % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** 从 ISO / datetime-local / 'HH:mm' 中取出 'HH:mm'；无有效时间返回空串。 */
export function clockOfIso(value: string | null | undefined): string {
  if (!value) return ''
  const m = /(\d{1,2}):(\d{2})/.exec(value)
  if (!m) return ''
  const h = Number(m[1])
  const min = Number(m[2])
  if (h > 23 || min > 59) return ''
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`
}

/** 用行程日 date 与 'HH:mm' 拼成后端需要的 ISO 字符串（YYYY-MM-DDTHH:mm:00）。
 *  dayOffset 处理跨天结束；缺少 date 时用固定基准日兜底，后端 normalize_times 会做最终校正。
 */
export function combineIso(date: string | null | undefined, hhmm: string, dayOffset = 0): string | null {
  const clock = /^(\d{1,2}):(\d{2})$/.exec((hhmm || '').trim())
  if (!clock) return null
  const datePart = /^(\d{4}-\d{2}-\d{2})/.exec((date || '').trim())
  const base = datePart ? datePart[1] : '1970-01-01'
  const d = new Date(`${base}T00:00:00`)
  if (Number.isNaN(d.getTime())) return `${base}T${hhmm}:00`
  d.setDate(d.getDate() + dayOffset)
  const y = d.getFullYear()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const da = String(d.getDate()).padStart(2, '0')
  return `${y}-${mo}-${da}T${String(clock[1]).padStart(2, '0')}:${clock[2]}:00`
}

/** 判定两个时间点是否重叠：只有结束严格大于开始才算。 */
export function overlaps(prevEndMin: number, nextStartMin: number): boolean {
  return prevEndMin > nextStartMin
}

/** 本地冲突判定所需的最小条目形状。 */
export interface TimeConflictItem {
  id: string
  day_id: string | null
  start_time: string | null
  end_time: string | null
  sort_key?: string
}

export interface LocalConflict {
  itemId: string
  withItemId: string
}

/** 前端即时冲突判定：按行程日分组、按开始时间排序，仅相邻项「前项结束 > 后项开始」才算冲突。
 *  与后端一致：前项 14:00 结束、后项 14:00 开始首尾相接不报冲突。
 */
export function findLocalConflicts(items: TimeConflictItem[]): LocalConflict[] {
  const byDay = new Map<string, TimeConflictItem[]>()
  for (const it of items) {
    if (!it.day_id) continue
    const arr = byDay.get(it.day_id) ?? []
    arr.push(it)
    byDay.set(it.day_id, arr)
  }
  const result: LocalConflict[] = []
  for (const arr of byDay.values()) {
    const timed = arr
      .map((it) => {
        const start = toMinutes(clockOfIso(it.start_time))
        let end = toMinutes(clockOfIso(it.end_time))
        // 结束钟点早于开始：视为跨到次日
        if (!Number.isNaN(start) && !Number.isNaN(end) && end < start) end += 1440
        return { it, start, end }
      })
      .filter((x) => !Number.isNaN(x.start) && !Number.isNaN(x.end) && x.end > x.start)
      .sort((a, b) => a.start - b.start
        || String(a.it.sort_key ?? '').localeCompare(String(b.it.sort_key ?? '')))
    for (let i = 1; i < timed.length; i++) {
      const prev = timed[i - 1]
      const next = timed[i]
      if (overlaps(prev.end, next.start)) {
        result.push({ itemId: next.it.id, withItemId: prev.it.id })
      }
    }
  }
  return result
}
