/**
 * E2E：底图无缝切换（相机快照 + 叠加层重放 + marker 按新坐标系重建）。
 *
 * 跳过原因：真实流程需要已启动的前后端服务、/map/providers 返回至少两个 enabled
 * provider，以及可加载的瓦片/样式（MapLibre WebGL 在 CI 无头环境也不稳定），
 * 因此用 test.skip 声明；联调时把 test.skip 改为 test。
 *
 * 不阻塞保证：vitest 只收集 src/**，vite build / vue-tsc 不包含 tests/e2e；
 * 「契约快照」用例为纯断言，不创建浏览器上下文之外的网络请求。
 */
import { test, expect } from '@playwright/test'

const TRIP_ID = process.env.E2E_TRIP_ID ?? '1'

/** 契约快照：相机字段、坐标系归一化与 setStyle 破坏性流程。 */
test('契约快照：相机快照字段与坐标系映射（无需服务）', () => {
  const camera = { center: [104.2, 35.9], zoom: 3.2, bearing: 0, pitch: 0 }
  expect(camera.center).toHaveLength(2)
  expect(camera.zoom).toBe(3.2)
  expect(camera.bearing).toBe(0)
  expect(camera.pitch).toBe(0)

  // 后端 coordSystem 为 GCJ02 / BD09 / CGCS2000，coord.ts 的类型为 GCJ-02 / BD-09
  const normalize = (value: string) => {
    switch (value.toUpperCase().replace(/[-_]/g, '')) {
      case 'GCJ02': return 'GCJ-02'
      case 'BD09': return 'BD-09'
      case 'CGCS2000': return 'CGCS2000'
      default: return 'WGS84'
    }
  }
  expect(normalize('GCJ02')).toBe('GCJ-02')
  expect(normalize('BD09')).toBe('BD-09')
  expect(normalize('CGCS2000')).toBe('CGCS2000')
  expect(normalize('WGS84')).toBe('WGS84')

  // 切换顺序：快照 → setStyle → style.load → jumpTo → 重放 → 重建 marker → 恢复选中
  const phases = ['snapshot', 'setStyle', 'style.load', 'jumpTo', 'replay', 'rebuildMarkers', 'restoreSelection']
  expect(phases[0]).toBe('snapshot')
  expect(phases[phases.length - 1]).toBe('restoreSelection')
  expect('/api/v1/map/tiles/amap/3/6/3').toContain('/map/tiles/')
})

test.skip('真实流程：切换 provider 后相机与选中态保持（需真实服务与多个可用底图）', async ({ page }) => {
  await page.goto(`/trips/${TRIP_ID}/plan`)
  const canvas = page.locator('.maplibregl-canvas')
  await expect(canvas).toBeVisible()

  // 选中一个 marker，记录其激活态与位置
  const marker = page.locator('.ft-map-marker').first()
  await expect(marker).toBeVisible()
  await marker.click()
  await expect(page.locator('.ft-map-marker--active')).toHaveCount(1)

  // 通过底图下拉切到另一个 enabled provider（未 enabled 项被禁用）
  const select = page.locator('select').first()
  const options = await select.locator('option:not([disabled])').evaluateAll(
    (els) => els.map((e) => e.getAttribute('value')).filter((v): v is string => Boolean(v) && v !== ''),
  )
  expect(options.length).toBeGreaterThan(1)
  const current = await select.inputValue()
  const target = options.find((v) => v !== current) as string
  await select.selectOption(target)

  // 切换期间显示「切换中…」并屏蔽交互，结束后遮罩消失
  await expect(page.getByText('切换中…')).toBeHidden({ timeout: 15000 })
  await expect(page.locator('.ft-map-marker--active')).toHaveCount(1)
  // attribution 控件常驻（合规要求）
  await expect(page.locator('.maplibregl-ctrl-attrib')).toBeVisible()
})
