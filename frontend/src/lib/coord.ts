/** 坐标枢纽：业务坐标统一 WGS84 入库，渲染时按底图坐标系反向转换。 */
import gcoord, { type CRSTypes } from 'gcoord'

export type CoordSystem = 'WGS84' | 'CGCS2000' | 'GCJ-02' | 'BD-09'

const TO_GCOORD: Record<CoordSystem, CRSTypes> = {
  WGS84: gcoord.WGS84,
  CGCS2000: gcoord.WGS84, // 与 WGS84 椭球几乎一致，Web 精度可近似互换
  'GCJ-02': gcoord.GCJ02,
  'BD-09': gcoord.BD09,
}

export function transform(lng: number, lat: number, from: CoordSystem, to: CoordSystem): [number, number] {
  if (from === to || (from === 'CGCS2000' && to === 'WGS84') || (from === 'WGS84' && to === 'CGCS2000')) {
    return [lng, lat]
  }
  const [x, y] = gcoord.transform([lng, lat], TO_GCOORD[from], TO_GCOORD[to])
  return [x, y]
}

/** POI 结果（高德 GCJ-02 / 百度 BD-09 / 天地图 CGCS2000）→ WGS84 入库 */
export function toWgs84(lng: number, lat: number, from: CoordSystem): [number, number] {
  return transform(lng, lat, from, 'WGS84')
}

/** 渲染：WGS84 → 当前底图坐标系（GCJ-02 瓦片上的点必须用 GCJ-02 才对齐） */
export function fromWgs84(lng: number, lat: number, to: CoordSystem): [number, number] {
  return transform(lng, lat, 'WGS84', to)
}

export const COORD_LABELS: Record<CoordSystem, string> = {
  WGS84: 'WGS84 (GPS/OSM)',
  CGCS2000: 'CGCS2000 (天地图)',
  'GCJ-02': 'GCJ-02 (高德)',
  'BD-09': 'BD-09 (百度)',
}
