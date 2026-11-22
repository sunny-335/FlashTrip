import { describe, expect, it } from 'vitest'
import { keyBetween, keysBetween, sortByKey } from './sortKey'

describe('keyBetween 单调性', () => {
  it('连续在末尾追加时始终严格递增且不重复', () => {
    const keys: string[] = []
    let last: string | null = null
    for (let i = 0; i < 200; i++) {
      const next = keyBetween(last, null)
      if (last !== null) expect(last < next).toBe(true)
      keys.push(next)
      last = next
    }
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('连续在开头插入时始终严格递减且不重复', () => {
    const keys: string[] = []
    let first: string | null = null
    for (let i = 0; i < 200; i++) {
      const next = keyBetween(null, first)
      if (first !== null) expect(next < first).toBe(true)
      keys.push(next)
      first = next
    }
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('插到两项之间时满足 before < new < after', () => {
    const before = keyBetween(null, null)
    const after = keyBetween(before, null)
    const middle = keyBetween(before, after)
    expect(before < middle).toBe(true)
    expect(middle < after).toBe(true)
    // 可反复在两键之间插入而不冲突
    const again = keyBetween(before, middle)
    expect(before < again).toBe(true)
    expect(again < middle).toBe(true)
  })

  it('端点组合 (null,null) 与单点组合均返回合法键', () => {
    expect(keyBetween(null, null).length).toBeGreaterThan(0)
    expect(keyBetween(null, 'a1').length).toBeGreaterThan(0)
    expect(keyBetween('a1', null).length).toBeGreaterThan(0)
  })
})

describe('keysBetween', () => {
  it('生成 count 个严格有序的键', () => {
    const keys = keysBetween(null, null, 20)
    expect(keys).toHaveLength(20)
    for (let i = 1; i < keys.length; i++) expect(keys[i - 1] < keys[i]).toBe(true)
  })

  it('落在给定两键之间', () => {
    const before = keyBetween(null, null)
    const after = keyBetween(before, null)
    const keys = keysBetween(before, after, 5)
    for (const k of keys) {
      expect(before < k).toBe(true)
      expect(k < after).toBe(true)
    }
  })
})

describe('sortByKey', () => {
  it('按 sort_key 字典序升序排列', () => {
    const rows = [
      { id: 'c', sort_key: 'a2' },
      { id: 'a', sort_key: 'a0' },
      { id: 'b', sort_key: 'a1' },
    ]
    expect(sortByKey(rows).map((r) => r.id)).toEqual(['a', 'b', 'c'])
  })

  it('返回新数组，不修改入参顺序', () => {
    const rows = [
      { id: 'x', sort_key: 'a1' },
      { id: 'y', sort_key: 'a0' },
    ]
    const sorted = sortByKey(rows)
    expect(sorted).not.toBe(rows)
    expect(rows.map((r) => r.id)).toEqual(['x', 'y'])
    expect(sorted.map((r) => r.id)).toEqual(['y', 'x'])
  })
})
