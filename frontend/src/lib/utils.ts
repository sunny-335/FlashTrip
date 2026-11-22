import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', weekday: 'short' })
}

export function formatMoney(amount: number | string | null | undefined, currency = 'CNY'): string {
  if (amount === null || amount === undefined) return '—'
  const n = Number(amount)
  return Number.isNaN(n) ? '—' : `${currency} ${n.toFixed(2)}`
}
