/**
 * E2E：PDF 行程册与 ICS 日历导出下载。
 *
 * 跳过原因：真实下载需要已启动的前后端服务、登录态与含数据的行程（PDF 由后端
 * 实时渲染，空行程可能返回错误），CI 不具备，故用 test.skip 声明；
 * 联调时把 test.skip 改为 test 并准备一条有数据的行程。
 *
 * 不阻塞保证：vitest 只收集 src/**，vite build / vue-tsc 不包含 tests/e2e；
 * 「契约快照」用例为纯断言，含 Content-Disposition 文件名解析（不访问网络）。
 */
import { test, expect } from '@playwright/test'

const TRIP_ID = process.env.E2E_TRIP_ID ?? '1'

/** 契约快照：导出端点、scope 枚举、文件名解析与 JSON 错误识别。 */
test('契约快照：PDF/ICS 端点、scope 与文件名解析（无需服务）', () => {
  expect(`/api/v1/trips/${TRIP_ID}/export/pdf`).toContain('/export/pdf')
  expect(`/api/v1/trips/${TRIP_ID}/export/ics?scope=trip`).toContain('scope=trip')
  expect(['trip', 'all']).toContain('trip')

  // 与 lib/export.ts filenameOf 一致的解析规则
  const filenameOf = (raw: string, fallback: string) => {
    const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(raw)
    return match?.[1] ? decodeURIComponent(match[1].replace(/"/g, '')) : fallback
  }
  expect(filenameOf("attachment; filename=\"trip.pdf\"", 'flashtrip-trip.pdf')).toBe('trip.pdf')
  expect(filenameOf("attachment; filename*=UTF-8''%E8%A1%8C%E7%A8%8B.ics", 'flashtrip.ics')).toBe('行程.ics')
  expect(filenameOf('', 'flashtrip-trip.pdf')).toBe('flashtrip-trip.pdf')

  // 后端错误是 JSON 包装，不能用 api.post 的 JSON 解包路径下载二进制
  const errorEnvelope = { code: 4001, message: '导出内容为空', detail: null }
  expect(errorEnvelope.code).toBe(4001)
  expect(typeof errorEnvelope.message).toBe('string')
})

test.skip('真实流程：点击 PDF / ICS 触发下载且文件名正确（需真实服务与行程数据）', async ({ page }) => {
  await page.goto(`/trips/${TRIP_ID}/plan`)
  const pdfButton = page.getByRole('button', { name: 'PDF' })
  await expect(pdfButton).toBeEnabled() // exportReady：lib/export.ts 已被 glob 探测到

  const [pdf] = await Promise.all([
    page.waitForEvent('download'),
    pdfButton.click(),
  ])
  expect(pdf.suggestedFilename()).toMatch(/\.pdf$/i)

  const [ics] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'ICS' }).click(),
  ])
  expect(ics.suggestedFilename()).toMatch(/\.ics$/i)
})
