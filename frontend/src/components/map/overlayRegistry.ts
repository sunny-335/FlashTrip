/** 叠加层注册表：setStyle 是破坏性操作，会销毁运行时 source/layer。
 *  切换前把自定义 source/layer 的 spec、z-order、marker（WGS84）、相机、选中态快照下来，
 *  切换后按 z-order 重放，并按「新坐标系」重建路线与 marker。
 *
 *  约定：所有自定义 source/layer 的 id 一律以 OVERLAY_PREFIX 开头，
 *  底图自带的 raster-{provider} 源不会被登记，从而可精确区分。
 */
import type {
  Map as MlMap,
  StyleSpecification,
  SourceSpecification,
  LayerSpecification,
  GeoJSONSource,
} from 'maplibre-gl'
import { fromWgs84, type CoordSystem } from '@/lib/coord'

export const OVERLAY_PREFIX = 'flashtrip-'
export const ROUTE_SOURCE_ID = 'flashtrip-route'
export const ROUTE_CASING_LAYER = 'flashtrip-route-casing'
export const ROUTE_LINE_LAYER = 'flashtrip-route-line'

/** marker 数据一律保存 WGS84 原始坐标，重建时再按新底图坐标系反转换。 */
export interface OverlayMarker {
  id: string
  lng: number
  lat: number
  title: string
  meta?: Record<string, unknown>
}

export interface CameraSnapshot {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
}

export interface SourceSnapshot {
  id: string
  spec: Record<string, unknown>
  z: number
}

export interface LayerSnapshot {
  id: string
  spec: Record<string, unknown>
  z: number
}

export interface OverlaySnapshot {
  camera: CameraSnapshot
  sources: SourceSnapshot[]
  layers: LayerSnapshot[]
  markers: OverlayMarker[]
  selectedId: string | null
}

type GeoJSONData = Parameters<GeoJSONSource['setData']>[0]

/** 按指定坐标系把 WGS84 点串连成 LineString；少于 2 个点时返回空集合。 */
export function buildRouteGeoJSON(markers: OverlayMarker[], coord: CoordSystem): unknown {
  const coordinates = markers
    .filter((m) => Number.isFinite(m.lng) && Number.isFinite(m.lat))
    .map((m) => fromWgs84(m.lng, m.lat, coord))
  const features = coordinates.length >= 2
    ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates } }]
    : []
  return { type: 'FeatureCollection', features }
}

/** 快照相机（jumpTo 可直接消费）。 */
export function captureCamera(map: MlMap): CameraSnapshot {
  const c = map.getCenter()
  return {
    center: [c.lng, c.lat],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  }
}

/** 从当前 style 抓取自定义 source/layer 的 spec 与 z-order（z = 在 layers 数组中的下标）。 */
export function snapshotOverlays(
  map: MlMap,
  markers: OverlayMarker[],
  selectedId: string | null,
): OverlaySnapshot {
  const style = (map.getStyle() ?? {}) as StyleSpecification
  const rawSources = (style.sources ?? {}) as Record<string, Record<string, unknown>>
  const rawLayers = (style.layers ?? []) as (LayerSpecification & { id: string })[]

  const sources: SourceSnapshot[] = Object.entries(rawSources)
    .filter(([id]) => id.startsWith(OVERLAY_PREFIX))
    .map(([id, spec], i) => ({ id, spec: clone(spec), z: i }))

  const layers: LayerSnapshot[] = rawLayers
    .map((spec, z) => ({ spec, z }))
    .filter(({ spec }) => String(spec?.id ?? '').startsWith(OVERLAY_PREFIX))
    .map(({ spec, z }) => ({ id: String(spec.id), spec: clone(spec as unknown as Record<string, unknown>), z }))

  return {
    camera: captureCamera(map),
    sources,
    layers,
    markers: markers.map((m) => ({ ...m })),
    selectedId,
  }
}

/**
 * 切换后按 z-order 重放 source/layer。
 * 路线 source 的 data 用「新坐标系」重建，避免 GCJ-02 底图上仍画 WGS84 折线造成偏移。
 */
export function restoreSourcesLayers(
  map: MlMap,
  snap: OverlaySnapshot,
  coord: CoordSystem,
): void {
  for (const s of [...snap.sources].sort((a, b) => a.z - b.z)) {
    if (map.getSource(s.id)) continue
    const spec: Record<string, unknown> = { ...s.spec }
    if (s.id === ROUTE_SOURCE_ID) spec.data = buildRouteGeoJSON(snap.markers, coord)
    map.addSource(s.id, spec as unknown as SourceSpecification)
  }
  for (const l of [...snap.layers].sort((a, b) => a.z - b.z)) {
    if (map.getLayer(l.id)) continue
    map.addLayer(l.spec as unknown as LayerSpecification)
  }
}

/** items 变化（非切底图）时只刷新路线数据，不触碰 style。 */
export function refreshRouteData(map: MlMap, markers: OverlayMarker[], coord: CoordSystem): void {
  const src = map.getSource(ROUTE_SOURCE_ID) as GeoJSONSource | undefined
  if (!src) return
  src.setData(buildRouteGeoJSON(markers, coord) as GeoJSONData)
}

/** 首次建图时登记路线 source + line/casing 两层；幂等。 */
export function ensureRouteLayers(map: MlMap, markers: OverlayMarker[], coord: CoordSystem): void {
  if (!map.getSource(ROUTE_SOURCE_ID)) {
    map.addSource(ROUTE_SOURCE_ID, {
      type: 'geojson',
      data: buildRouteGeoJSON(markers, coord) as GeoJSONData,
    } as unknown as SourceSpecification)
  } else {
    refreshRouteData(map, markers, coord)
  }
  if (!map.getLayer(ROUTE_CASING_LAYER)) {
    map.addLayer({
      id: ROUTE_CASING_LAYER,
      type: 'line',
      source: ROUTE_SOURCE_ID,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#ffffff', 'line-width': 5, 'line-opacity': 0.85 },
    } as unknown as LayerSpecification)
  }
  if (!map.getLayer(ROUTE_LINE_LAYER)) {
    map.addLayer({
      id: ROUTE_LINE_LAYER,
      type: 'line',
      source: ROUTE_SOURCE_ID,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#0e9f8e', 'line-width': 2.5, 'line-opacity': 0.95 },
    } as unknown as LayerSpecification)
  }
}

function clone<T>(value: T): T {
  try {
    return JSON.parse(JSON.stringify(value)) as T
  } catch {
    return value
  }
}
