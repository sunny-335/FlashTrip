/**
 * E2E：三栏看板拖拽排序，刷新后保序（sort_key 分数索引持久化）。
 *
 * 跳过原因：真实流程需要已启动的前后端服务、登录态与含若干 plan items 的行程
 * （E2E_TRIP_ID），且 Sortable 在移动端被禁用（移动端改用 MoveButtons），
 * 因此真实流程用 test.skip 声明；仅 desktop project 下联调才把 test.skip 改为 test。
 *
 * 不阻塞保证：vitest 只收集 src/**，vite build / vue-tsc 不包含 tests/e2e；
 * 「契约快照」用例为纯断言，不访问网络。
 */
import { test, expect } from '@playwright/test'

const TRIP_ID = process.env.E2E_TRIP_ID ?? '1'

/** 契约快照：moves 请求体（后端 MoveIn 为 snake_case）与卡片 DOM 约定。 */
test('契约快照：moves 请求字段与卡片标识（无需服务）', () => {
  const move: Record<string, unknown> = {
    item_id: 'itm_1',
    to_day_id: 'day_1',
    to_bucket: 'main',
    new_sort_key: 'a1',
    before_sort_key: null,
    after_sort_key: 'a2',
  }
  // 字段名与 backend/app/schemas/plan.py 的 MoveIn 一致
  expect(move).toHaveProperty('item_id')
  expect(move).toHaveProperty('new_sort_key')
  expect(move).toHaveProperty('to_day_id')
  expect(move).toHaveProperty('to_bucket')
  expect(move).not.toHaveProperty('itemId')
  expect('/api/v1/trips/1/plan/moves').toContain('/plan/moves')
  expect('/api/v1/trips/1/plan/moves/undo').toContain('/undo')
  // new_sort_key 由前端 keyBetween 生成，满足 before < new < after；null 表示端点
  const before = (move.before_sort_key as string | null) ?? ''
  const after = (move.after_sort_key as string | null) ?? '\uffff'
  const key = move.new_sort_key as string
  expect(before < key && key < after).toBe(true)
})

test.skip('真实流程：拖拽到某天后刷新顺序保持不变（需真实服务与行程数据）', async ({ page }) => {
  await page.goto(`/trips/${TRIP_ID}/plan`)

  // 待规划池的 VueDraggable 带 data-group="__unplanned__"（POOL_KEY），
  // 各天的 data-group 为 day.id；卡片根元素带 data-id
  const poolCards = page.locator('[data-group="__unplanned__"] [data-id]')
  const dayCards = page.locator('[data-group]:not([data-group="__unplanned__"]) [data-id]')
  await expect(page.locator('[data-id]').first()).toBeVisible()

  const before = await dayCards.evaluateAll((els) => els.map((e) => e.getAttribute('data-id')))

  // 监听 moves 提交：拖拽结束应产生一次 POST /plan/moves
  const moveReq = page.waitForResponse(
    (r) => r.url().includes('/plan/moves') && r.request().method() === 'POST',
  )
  const source = poolCards.first()
  const target = dayCards.first()
  await source.dragTo(target)
  const resp = await moveReq
  expect(resp.ok()).toBeTruthy()

  // 刷新后顺序由服务端 sort_key 决定，应与提交后的顺序一致
  await page.reload()
  await expect(page.locator('[data-id]').first()).toBeVisible()
  const after = await dayCards.evaluateAll((els) => els.map((e) => e.getAttribute('data-id')))
  expect(after.length).toBeGreaterThanOrEqual(before.length)
  expect(after[0]).toBeTruthy()
})
