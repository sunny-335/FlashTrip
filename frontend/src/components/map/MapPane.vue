<script setup lang="ts">
/** 地图主容器：MapLibre GL 统一渲染引擎。
 *  - 底图来自 /map/providers（脱敏），raster 瓦片走后端 /map/tiles/... 代理，前端 style 不含密钥；
 *  - plan items 坐标为 WGS84，落点 / 连线前按当前底图 coordSystem 用 fromWgs84() 反转换；
 *  - 切底图交给 useMapSwitch（快照相机 + 叠加层 + marker + 选中态 → setStyle → 重放 → 回滚）；
 *  - attribution 使用 MapLibre 原生控件常驻，并额外展示审图号与合规文案。
 */
import 'maplibre-gl/dist/maplibre-gl.css'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import type { Map as MlMap, Marker as MlMarker, StyleSpecification } from 'maplibre-gl'
import { useRoute } from 'vue-router'
import { Loader2, MapPin } from 'lucide-vue-next'
import { COORD_LABELS, fromWgs84, type CoordSystem } from '@/lib/coord'
import { useMapStore, normalizeCoord, styleForProvider } from '@/stores/map'
import { usePlanStore, type PlanItem } from '@/stores/plan'
import { PLAN_CTX } from '@/composables/usePlanDnd'
import MapProviderSwitcher from './MapProviderSwitcher.vue'
import PoiSearchBox from './PoiSearchBox.vue'
import { useMapSwitch, type AppliedStyle } from './useMapSwitch'
import {
  ensureRouteLayers,
  refreshRouteData,
  type OverlayMarker,
} from './overlayRegistry'

/** 兼容 PlanBoard 传入的 PlanItem[]，也接受 FootprintsView 的 moment 精简对象。 */
interface MapItemLike {
  id: string
  lng?: number | null
  lat?: number | null
  title?: string | null
  subtitle?: string | null
  type?: string | null
  day_id?: string | null
}

const props = withDefaults(
  defineProps<{ items?: MapItemLike[]; showTools?: boolean }>(),
  { items: () => [], showTools: true },
)

const route = useRoute()
const mapStore = useMapStore()
const planStore = usePlanStore()
const planCtx = inject(PLAN_CTX, null)
const tripId = computed(() => String(route.params.tripId ?? ''))

const container = ref<HTMLElement | null>(null)
let mapInstance: MlMap | null = null
let domMarkers: MlMarker[] = []
let markerEls: Record<string, HTMLElement> = {}
let currentMarkers: OverlayMarker[] = []

const styleReady = ref(false)
const initError = ref('')
const notice = ref('')
const switchRevision = ref(0)
const applied = ref<AppliedStyle | null>(null)
const selectedId = ref<string | null>(null)

const coordLabel = computed(() => COORD_LABELS[normalizeCoord(mapStore.currentProvider?.coordSystem)] ?? 'WGS84')
const attribution = computed(() => mapStore.currentProvider?.attribution ?? '© OpenStreetMap contributors')
const auditNumber = computed(() => mapStore.auditNumber || mapStore.currentProvider?.auditNumber || '')
const complianceNote = computed(
  () => mapStore.complianceNote || mapStore.currentProvider?.complianceNote || '',
)

function toOverlayMarkers(items: MapItemLike[] | undefined): OverlayMarker[] {
  return (items ?? [])
    .filter((i) => i && typeof i.lng === 'number' && typeof i.lat === 'number'
      && Number.isFinite(i.lng) && Number.isFinite(i.lat))
    .map((i) => ({
      id: String(i.id),
      lng: i.lng as number,
      lat: i.lat as number,
      title: String(i.title ?? i.subtitle ?? '地点'),
      meta: { type: i.type ?? null, day_id: i.day_id ?? null },
    }))
}

function createMarkerElement(m: OverlayMarker, active: boolean): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.className = 'ft-map-marker' + (active ? ' ft-map-marker--active' : '')
  el.title = m.title
  const dot = document.createElement('span')
  dot.className = 'ft-map-marker__dot'
  const label = document.createElement('span')
  label.className = 'ft-map-marker__label'
  label.textContent = m.title
  el.append(dot, label)
  return el
}

function applySelection(): void {
  for (const [id, el] of Object.entries(markerEls)) {
    el.classList.toggle('ft-map-marker--active', id === selectedId.value)
  }
}

/** DOM Marker 保守策略：全部 remove 后按新坐标系重建。 */
function rebuildMarkers(list: OverlayMarker[], coord: CoordSystem): void {
  if (!mapInstance) return
  for (const mk of domMarkers) mk.remove()
  domMarkers = []
  markerEls = {}
  currentMarkers = list.map((m) => ({ ...m }))
  for (const m of currentMarkers) {
    const [x, y] = fromWgs84(m.lng, m.lat, coord)
    const el = createMarkerElement(m, m.id === selectedId.value)
    const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
      .setLngLat([x, y])
      .addTo(mapInstance)
    el.addEventListener('click', (ev) => {
      ev.stopPropagation()
      selectedId.value = m.id
      applySelection()
    })
    domMarkers.push(marker)
    markerEls[m.id] = el
  }
}

const switcher = useMapSwitch({
  getMap: () => mapInstance,
  getMarkers: () => currentMarkers,
  getSelectedId: () => selectedId.value,
  rebuildMarkers,
  restoreSelection: (id) => {
    selectedId.value = id
    applySelection()
  },
  getApplied: () => applied.value,
  onApplied: (target) => {
    applied.value = { style: target.style, coord: target.coord }
    mapStore.select(target.providerId)
  },
})

// 顶层 ref：模板自动解包，避免深层访问 .value
const switching = switcher.switching
const visibleCount = computed(() => toOverlayMarkers(props.items).length)

watch(switching, (v) => { mapStore.switching = v })

async function onSwitchProvider(id: string): Promise<void> {
  const p = mapStore.providers.find((x) => x.id === id)
  if (!p || !p.enabled || !mapInstance) return
  const ok = await switcher.switchTo({
    providerId: p.id,
    style: styleForProvider(p),
    coord: normalizeCoord(p.coordSystem),
  })
  // 无论成败都让下拉重建，失败时自动回显到仍生效的底图
  switchRevision.value += 1
  if (!ok && switcher.error.value) initError.value = switcher.error.value
  else if (ok) initError.value = ''
}

function onPoiAdded(item: PlanItem): void {
  try {
    planStore.insertLocal(item)
    planCtx?.dnd.rebuild()
    notice.value = '已加入待规划池'
  } catch {
    notice.value = '已加入待规划池，刷新看板后可见'
  }
  window.setTimeout(() => { notice.value = '' }, 2600)
}

function syncItems(): void {
  if (!mapInstance || !styleReady.value || switcher.switching.value) return
  const coord = applied.value?.coord ?? 'WGS84'
  const pts = toOverlayMarkers(props.items)
  refreshRouteData(mapInstance, pts, coord)
  rebuildMarkers(pts, coord)
}

watch(() => props.items, syncItems)

onMounted(async () => {
  await mapStore.load()
  if (!container.value) return
  const provider = mapStore.currentProvider
  // 列表为空时仍可渲染（用免 token 的 OpenFreeMap 兜底），attribution 常驻
  const style = provider ? styleForProvider(provider) : 'https://tiles.openfreemap.org/styles/liberty'
  const coord: CoordSystem = provider ? normalizeCoord(provider.coordSystem) : 'WGS84'
  applied.value = { style, coord }

  try {
    mapInstance = new maplibregl.Map({
      container: container.value,
      style: style as unknown as string | StyleSpecification,
      center: [104.2, 35.9],
      zoom: 3.2,
      attributionControl: true,
    })
    mapInstance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    mapInstance.on('load', () => {
      if (!mapInstance) return
      styleReady.value = true
      const pts = toOverlayMarkers(props.items)
      ensureRouteLayers(mapInstance, pts, coord)
      rebuildMarkers(pts, coord)
      if (pts.length > 1) {
        const bounds = new maplibregl.LngLatBounds()
        for (const m of pts) bounds.extend(fromWgs84(m.lng, m.lat, coord))
        mapInstance.fitBounds(bounds, { padding: 48, maxZoom: 13, duration: 0 })
      } else if (pts.length === 1) {
        mapInstance.setCenter(fromWgs84(pts[0].lng, pts[0].lat, coord))
        mapInstance.setZoom(11)
      }
    })
    mapInstance.on('error', (e) => {
      // 瓦片 404 等不打断使用，仅记录到状态栏
      if (!mapStore.error) initError.value = e?.error?.message || '部分底图瓦片加载失败'
    })
  } catch (e) {
    initError.value = (e as Error)?.message || '地图初始化失败'
  }
})

onBeforeUnmount(() => {
  for (const mk of domMarkers) mk.remove()
  domMarkers = []
  mapInstance?.remove()
  mapInstance = null
})
</script>

<template>
  <div class="relative h-full w-full overflow-hidden rounded-lg border border-border bg-muted/40">
    <div ref="container" class="absolute inset-0" />

    <!-- 左上：底图切换 + POI 搜索 -->
    <div v-if="showTools" class="absolute left-2 top-2 z-10 flex w-[248px] flex-col gap-2">
      <MapProviderSwitcher
        :key="switchRevision"
        :model-value="mapStore.currentProviderId"
        :providers="mapStore.providers"
        :switching="switching"
        :coord-label="coordLabel"
        @change="onSwitchProvider"
      />
      <PoiSearchBox
        v-if="tripId"
        :trip-id="tripId"
        :providers="mapStore.poiProviders"
        @added="onPoiAdded"
      />
    </div>

    <!-- 左下：合规 / attribution 补充（原生 AttributionControl 常驻右下） -->
    <div class="pointer-events-none absolute bottom-1 left-2 z-10 flex max-w-[70%] flex-col gap-0.5 text-[10px] leading-tight text-foreground/80">
      <span class="w-fit rounded bg-card/85 px-1.5 py-0.5 shadow-sm">{{ attribution }}</span>
      <span v-if="auditNumber" class="w-fit rounded bg-card/85 px-1.5 py-0.5 shadow-sm">审图号：{{ auditNumber }}</span>
      <span v-if="complianceNote" class="line-clamp-2 w-fit rounded bg-card/85 px-1.5 py-0.5 shadow-sm text-muted-foreground">
        {{ complianceNote }}
      </span>
    </div>

    <!-- 底部地点计数 -->
    <div class="pointer-events-none absolute right-2 top-2 z-10 flex items-center gap-1 rounded bg-card/90 px-2 py-1 text-[10px] text-muted-foreground shadow-sm">
      <MapPin class="h-3 w-3" /> {{ visibleCount }} 个地点 · {{ coordLabel }}
    </div>

    <p v-if="notice" class="absolute left-1/2 top-2 z-20 -translate-x-1/2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs shadow-sm">
      {{ notice }}
    </p>
    <p v-if="initError" class="absolute bottom-8 left-2 z-20 max-w-[80%] rounded-lg border border-destructive/40 bg-card px-2 py-1 text-[11px] text-destructive shadow-sm">
      {{ initError }}
    </p>

    <!-- 切换中：屏蔽交互 -->
    <div
      v-if="switching"
      class="absolute inset-0 z-30 grid place-items-center bg-card/55 backdrop-blur-[1px]"
    >
      <div class="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-sm">
        <Loader2 class="h-3.5 w-3.5 animate-spin text-primary" /> 切换中…
      </div>
    </div>
  </div>
</template>

<style>
/* 动态插入的 DOM Marker 不受 scoped 作用域影响，使用带前缀的全局类。 */
.ft-map-marker {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: #1c211f;
}
.ft-map-marker__dot {
  width: 12px;
  height: 12px;
  border-radius: 9999px;
  background: #0e9f8e;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  flex: none;
  transition: transform 0.12s ease;
}
.ft-map-marker__label {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  line-height: 16px;
  padding: 0 5px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e4e8e5;
}
.ft-map-marker--active .ft-map-marker__dot {
  transform: scale(1.35);
  background: #0b6f63;
}
.ft-map-marker--active .ft-map-marker__label {
  background: #0e9f8e;
  color: #fff;
  border-color: #0e9f8e;
}
</style>
