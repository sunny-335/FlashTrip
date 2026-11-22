/** 拖拽排序键：fractional indexing，前后端同一算法（后端 plan_service 亦用 base62）。 */
import { generateKeyBetween, generateNKeysBetween } from 'fractional-indexing'

export function keyBetween(before: string | null, after: string | null): string {
  return generateKeyBetween(before ?? null, after ?? null)
}

export function keysBetween(before: string | null, after: string | null, count: number): string[] {
  return generateNKeysBetween(before ?? null, after ?? null, count)
}

export function sortByKey<T extends { sort_key: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => (a.sort_key < b.sort_key ? -1 : a.sort_key > b.sort_key ? 1 : 0))
}
