import { describe, expect, it } from 'vitest'
import { fromWgs84, toWgs84, transform } from './coord'

/** 两点球面距离（米），用于校验往返误差。 */
function distanceM(a: [number, number], b: [number, number]): number {
  const R = 6371000
  const rad = (d: number) => (d * Math.PI) / 180
  const dLat = rad(b[1] - a[1])
  const dLng = rad(b[0] - a[0])
  const la1 = rad(a[1])
  const la2 = rad(b[1])
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

// 国内若干已知点（GCJ-02 坐标）
const POINTS: [number, number][] = [
  [116.397428, 39.90923], // 北京
  [121.473701, 31.230416], // 上海
  [113.264385, 23.129112], // 广州
  [104.066541, 30.572269], // 成都
  [114.057868, 22.543096], // 深圳
]

describe('GCJ-02 ↔ WGS84 往返', () => {
  it('toWgs84 → fromWgs84 回到 GCJ-02，误差 < 1 米', () => {
    for (const p of POINTS) {
      const wgs = toWgs84(p[0], p[1], 'GCJ-02')
      const back = fromWgs84(wgs[0], wgs[1], 'GCJ-02')
      expect(distanceM(p, back)).toBeLessThan(1)
    }
  })

  it('WGS84 → GCJ-02 → WGS84 往返误差 < 1 米', () => {
    for (const p of POINTS) {
      const gcj = transform(p[0], p[1], 'WGS84', 'GCJ-02')
      const wgs = transform(gcj[0], gcj[1], 'GCJ-02', 'WGS84')
      expect(distanceM(p, wgs)).toBeLessThan(1)
    }
  })

  it('GCJ-02 转换确实产生偏移（不是直通）', () => {
    const [lng, lat] = POINTS[0]
    const wgs = toWgs84(lng, lat, 'GCJ-02')
    expect(distanceM([lng, lat], wgs)).toBeGreaterThan(50)
  })
})

describe('BD-09 往返', () => {
  it('BD-09 → WGS84 → BD-09 误差 < 1 米', () => {
    for (const p of POINTS) {
      const wgs = toWgs84(p[0], p[1], 'BD-09')
      const back = fromWgs84(wgs[0], wgs[1], 'BD-09')
      expect(distanceM(p, back)).toBeLessThan(1)
    }
  })
})

describe('CGCS2000 直通', () => {
  it('CGCS2000 ↔ WGS84 不转换，坐标原样返回', () => {
    const p: [number, number] = [116.397428, 39.90923]
    expect(transform(p[0], p[1], 'CGCS2000', 'WGS84')).toEqual(p)
    expect(transform(p[0], p[1], 'WGS84', 'CGCS2000')).toEqual(p)
    expect(toWgs84(p[0], p[1], 'CGCS2000')).toEqual(p)
  })

  it('同坐标系转换原样返回', () => {
    const p: [number, number] = [121.473701, 31.230416]
    expect(transform(p[0], p[1], 'GCJ-02', 'GCJ-02')).toEqual(p)
  })
})
