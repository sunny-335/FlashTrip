<script setup lang="ts">
/** 地图主容器：MapLibre GL 统一渲染引擎。
 *  - 唯一底图来源：/map/config 的 defaultProviderId（在全局设置里配置），行程页不再渲染底图下拉；
 *  - 初始化：style 直接传给 new Map({style})，style.styleUrl 存在时用其 URL 字符串，
 *    首次 style.load（load 事件）完成后才追加业务叠加层，避免空 style 上 addSource 报错；
 *  - plan items 坐标为 WGS84，落点 / 连线前按当前底图 coordSystem 用 fromWgs84() 反转换；
 *  - 页脚只居中显示当前 provider 的 attribution，MapLibre 原生 attributionControl 保留；
 *  - 底图无缝切换：useMapSwitch 快照相机 / source / layer / marker / 选中态 → setStyle →
 *    style.load 后重放 → 按新坐标系重建 marker → 异常回滚 prevStyle，全程显示「切换中」。
 */
import 'maplibre-gl/dist/maplibre-gl.css'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import type { Map as MlMap, Marker as MlMarker, StyleSpecification } from 'maplibre-gl'
import { useRoute } from 'vue-router'
import { Loader2 } from 'lucide-vue-next'
import { fromWgs84, type CoordSystem } from '@/lib/coord'
import {
  useMapStore, normalizeCoord, styleForProvider,
} from '@/stores/map'
import { usePlanStore, type PlanItem } from '@/stores/plan'
import { PLAN_CTX } from '@/composables/usePlanDnd'
import PoiSearchBox from './PoiSearchBox.vue'
import { useMapSwitch, type AppliedStyle } from './useMapSwitch'
import {
  ensureRouteLayers,
  refreshRouteData,
  type OverlayMarker,
} from './overlayRegistry'

/** 兼容 PlanBoard 传入的 PlanItem[]，也接受其他视图的精简坐标对象。 */
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
/** 当前已应用到画布的 provider id：避免 select() 回写时重复触发 watch 切换。 */
let activeProviderId = ''

const styleReady = ref(false)
const initError = ref('')
const notice = ref('')
const applied = ref<AppliedStyle | null>(null)
const selectedId = ref<string | null>(null)

/** 页脚署名：跟随当前 provider，切换底图时自动更新。 */
const attribution = computed(
  () => mapStore.currentProvider?.attribution ?? '© OpenStreetMap contributors',
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

/** DOM Marker 保守策略：全部 remove 后按新坐标系重建，坐标一律 WGS84 → 当前坐标系。 */
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
    // 供外层（如足迹页）捕获 marker 点击后按条目 id 进入行程记忆：只补 DOM 标识，不改渲染逻辑
    const domEl = marker.getElement()
    domEl.setAttribute('data-item-id', m.id)
    domEl.setAttribute('title', m.title)
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
    activeProviderId = target.providerId
    mapStore.select(target.providerId)
  },
})

// 顶层 ref：模板自动解包
const switching = switcher.switching

watch(switching, (v) => { mapStore.switching = v })

/** 运行期若默认底图被改动（如全局设置切换 provider），走快照/重放机制无缝切换，页脚随之更新。 */
watch(() => mapStore.currentProviderId, async (id) => {
  if (!id || !mapInstance || !styleReady.value || id === activeProviderId) return
  const p = mapStore.providers.find((x) => x.id === id)
  if (!p || !p.enabled) return
  try {
    const ok = await switcher.switchTo({
      providerId: p.id,
      style: styleForProvider(p),
      coord: normalizeCoord(p.coordSystem),
    })
    if (!ok && switcher.error.value) initError.value = switcher.error.value
    else if (ok) initError.value = ''
  } catch (e) {
    initError.value = (e as Error)?.message || '地图样式无效'
  }
})

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
  // 行程页唯一底图：/map/config 的 defaultProviderId 对应的 provider
  const provider = mapStore.defaultProvider ?? mapStore.currentProvider
  if (!provider) {
    initError.value = mapStore.error || '未配置可用的地图供应商'
    return
  }

  try {
    const style = styleForProvider(provider)
    const coord: CoordSystem = normalizeCoord(provider.coordSystem)
    activeProviderId = provider.id
    applied.value = { style, coord }
    if (mapStore.currentProviderId !== provider.id) mapStore.select(provider.id)

    // style 必须直接传入构造参数：矢量 styleUrl 用 URL 字符串，raster 代理用 style 对象
    mapInstance = new maplibregl.Map({
      container: container.value,
      style: style as unknown as string | StyleSpecification,
      center: [104.2, 35.9],
      zoom: 3.2,
      attributionControl: {},
    })
    mapInstance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    // 首次 style.load 完成（MapLibre 的 load 事件）后再登记路线图层与 marker
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
  <!-- h-full + 明确 min-h：容器高度链不断裂，canvas 不会被压成 0 高度 -->
  <div class="relative h-full w-full min-h-[160px] overflow-hidden rounded-lg border border-border bg-muted/40">
    <!--
      MapLibre 会给容器追加 .maplibregl-map 类，其样式表里 position:relative 会覆盖
      Tailwind 的 absolute（两者特异度相同、后加载者胜），导致容器高度塌成 0。
      因此这里不用 absolute inset-0，改用 h-full w-full 让高度直接来自父级。
    -->
    <div ref="container" class="h-full w-full" />

    <!-- 地图上方正中间：紧凑搜索框，结果以浮层下拉展示，不铺满遮挡地图 -->
    <div v-if="showTools" class="absolute left-1/2 top-2 z-20 w-[min(92%,340px)] -translate-x-1/2">
      <PoiSearchBox
        v-if="tripId"
        :trip-id="tripId"
        :providers="mapStore.poiProviders"
        @added="onPoiAdded"
      />
    </div>

    <!-- 页脚：只居中显示当前底图 provider 的署名，切换 provider 时自动跟随 -->
    <div class="pointer-events-none absolute inset-x-0 bottom-1 z-10 flex justify-center px-2">
      <span class="rounded bg-card/85 px-1.5 py-0.5 text-center text-[10px] leading-tight text-foreground/80 shadow-sm">
        {{ attribution }}
      </span>
    </div>

    <p v-if="notice" class="absolute left-1/2 top-14 z-20 -translate-x-1/2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs shadow-sm">
      {{ notice }}
    </p>
    <p v-if="initError" class="absolute bottom-8 left-1/2 z-20 max-w-[80%] -translate-x-1/2 rounded-lg border border-destructive/40 bg-card px-2 py-1 text-[11px] text-destructive shadow-sm">
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
