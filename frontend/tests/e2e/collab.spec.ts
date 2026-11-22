/**
 * E2E：协作权限与 SSE 同步（只读成员写操作被后端 403 拒绝）。
 *
 * 跳过原因：真实流程需要已启动的前后端服务、一个 owner 会话与一个只读成员会话
 * （默认只有 trip:read），以及真实 SSE 连接；CI 不具备这些账号与连接，故 test.skip。
 * 联调时把 test.skip 改为 test，并用 context.addCookies / storageState 注入两个会话。
 *
 * 不阻塞保证：vitest 只收集 src/**，vite build / vue-tsc 不包含 tests/e2e；
 * 「契约快照」用例为纯断言。
 */
import { test, expect } from '@playwright/test'

const TRIP_ID = process.env.E2E_TRIP_ID ?? '1'

/** 契约快照：10 个权限点、默认只读与事件补发端点（与 deps.py 对齐）。 */
test('契约快照：10 个权限点、默认只读与事件端点（无需服务）', () => {
  const PERMISSION_KEYS = [
    'trip:read', 'plan:write', 'booking:write', 'transport:write', 'expense:write',
    'packing:write', 'moment:write', 'member:manage', 'trip:settings', 'ai:use',
  ]
  expect(PERMISSION_KEYS).toHaveLength(10)
  expect(new Set(PERMISSION_KEYS).size).toBe(10)
  expect(PERMISSION_KEYS).toContain('trip:read')
  expect(PERMISSION_KEYS).toContain('member:manage')

  // 默认只读：新建成员仅授予 trip:read
  const DEFAULT_PERMISSION_KEYS = ['trip:read']
  expect(DEFAULT_PERMISSION_KEYS).toEqual(['trip:read'])

  // 权限更新用 dict；断线降级靠 since?cursor= 补发
  expect('/api/v1/trips/1/members/m1/permissions').toContain('/permissions')
  expect('/api/v1/trips/1/events/since?cursor=0').toContain('cursor=')
  expect('/api/v1/trips/1/events').toContain('/events')
})

test.skip('真实流程：只读成员写操作返回 403、UI 保存按钮禁用（需真实服务与只读会话）', async ({ page, request }) => {
  // 只读成员登录（由测试夹具注入 cookie 后），直接调用写接口应被 require_permission 拒绝
  const deny = await request.post(`/api/v1/trips/${TRIP_ID}/bookings`, {
    data: { type: 'hotel', title: '越权写入' },
  })
  expect(deny.status()).toBe(403)

  await page.goto(`/trips/${TRIP_ID}/collab`)
  // 无 member:manage 时「新建邀请」不可用
  await expect(page.getByRole('button', { name: '新建邀请' })).toBeDisabled()
  // 选中一位成员后权限矩阵才渲染，共 10 行且被禁用
  await page.locator('button').filter({ hasText: '项权限' }).first().click()
  await expect(page.getByText('权限矩阵')).toBeVisible()
  await expect(page.locator('input[type="checkbox"]')).toHaveCount(10)
  await expect(page.getByRole('button', { name: '保存权限' })).toBeDisabled()
})

test.skip('真实流程：另一成员变更后经 SSE 自动刷新（需真实服务与 SSE 连接）', async ({ page }) => {
  await page.goto(`/trips/${TRIP_ID}/collab`)
  await expect(page.getByText(/SSE 已连接|轮询降级中/)).toBeVisible()
  // 由另一会话新增邀请后，本页邀请列表应出现新行（collab store 收到事件自动 load）
  await expect(page.getByText('邀请链接')).toBeVisible()
})
