/** 地图底图状态：脱敏 provider 列表、默认底图与坐标系。
 *  后端 /map/providers 与 /map/config 的字段原样接入；密钥只在后端，前端 style 不含密钥。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/lib/api'
import type { CoordSystem } from '@/lib/coord'

/** 后端 style 是 MapLibre StyleSpecification 的子集（vector 引用式 / raster 代理式）。 */
export interface MapStyleSpec {
  version: number
  name?: string
  sources?: Record<string, unknown>
  layers?: Record<string, unknown>[]
  styleUrl?: string | null
  coordSystem?: string
  [key: string]: unknown
}

/** 对齐 list_providers() 输出（camelCase 字段，脱敏：只有 hasKey / enabled）。 */
export interface MapProvider {
  id: string
  label: string
  styleUrl: string | null
  tileUrlTemplate: string | null
  coordSystem: string
  attribution: string
  needsToken: boolean
  auditNumber: string
  enabled: boolean
  hasKey: boolean
  complianceNote: string
  style: MapStyleSpec
}

/** 对齐 /map/config 输出。 */
export interface MapConfig {
  auditNumber: string
  defaultProviderId: string
  providers: MapProvider[]
  // 后端 /map/config 不返回合规文案，保留可选字段仅为兼容旧构建
  complianceNote?: string
}

/** 后端 coordSystem 值为 WGS84 / GCJ02 / BD09 / CGCS2000，需映射到 coord.ts 的类型。 */
export function normalizeCoord(value?: string | null): CoordSystem {
  switch ((value ?? '').toUpperCase().replace(/[-_]/g, '')) {
    case 'GCJ02': return 'GCJ-02'
    case 'BD09': return 'BD-09'
    case 'CGCS2000': return 'CGCS2000'
    default: return 'WGS84'
  }
}

/** 有 POI 搜索能力的国内供应商（后端 pick_provider 白名单）。 */
export const POI_PROVIDER_IDS = ['amap', 'tianditu']

/** 初始化兜底仅供短暂加载状态；正式地图必须使用服务端下发的合规 Provider 样式。 */
export const DEFAULT_VECTOR_STYLE_URL = ''

/**
 * 生成传给 new maplibregl.Map({ style }) / map.setStyle 的值：
 * - style.styleUrl 存在（OpenFreeMap 等矢量引用式）→ 必须直接返回该 URL 字符串，
 *   否则把「sources/layers 为空」的 style 对象交给 MapLibre 会得到一张空白地图；
 * - 高德 / 天地图（raster 代理式）→ 返回后端下发的 raster style 对象，
 *   瓦片已指向 /map/tiles/... 代理路径，URL 内不含密钥；
 * - 信息缺失时回退到免密钥矢量 style，避免空白。
 */
export function styleForProvider(p: MapProvider): string | MapStyleSpec {
  const styleUrl = p.style?.styleUrl || (!p.tileUrlTemplate ? p.styleUrl : null)
  if (styleUrl) return String(styleUrl)
  if (p.style && (p.style.version || p.style.sources)) return p.style
  return DEFAULT_VECTOR_STYLE_URL
}

export const useMapStore = defineStore('map', () => {
  const providers = ref<MapProvider[]>([])
  const auditNumber = ref('')
  const complianceNote = ref('')
  const defaultProviderId = ref('')
  const currentProviderId = ref('')
  const switching = ref(false)
  const selectedId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')

  const currentProvider = computed<MapProvider | null>(
    () => providers.value.find((p) => p.id === currentProviderId.value) ?? null,
  )
  /** /map/config 的 defaultProviderId 对应的底图：行程页唯一底图来源。 */
  const defaultProvider = computed<MapProvider | null>(
    () => providers.value.find((p) => p.id === defaultProviderId.value && p.enabled)
      ?? providers.value.find((p) => p.enabled)
      ?? null,
  )
  const currentCoord = computed<CoordSystem>(() => normalizeCoord(currentProvider.value?.coordSystem))
  const enabledProviders = computed(() => providers.value.filter((p) => p.enabled))
  const poiProviders = computed(() =>
    providers.value.filter((p) => POI_PROVIDER_IDS.includes(p.id) && p.enabled),
  )

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const [list, cfg] = await Promise.all([
        api.get<MapProvider[]>('/map/providers'),
        api.get<MapConfig>('/map/config').catch(() => null),
      ])
      providers.value = Array.isArray(list) ? list : []
      if (cfg) {
        auditNumber.value = cfg.auditNumber || ''
        complianceNote.value = cfg.complianceNote || ''
        defaultProviderId.value = cfg.defaultProviderId || ''
      }
      const preferred = defaultProviderId.value
      const fallback =
        providers.value.find((p) => p.id === preferred && p.enabled)?.id ??
        providers.value.find((p) => p.enabled)?.id ?? ''
      if (!currentProviderId.value || !providers.value.some((p) => p.id === currentProviderId.value && p.enabled)) {
        currentProviderId.value = fallback
      }
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  /** 选中底图；未 enabled（含 Mapbox 未填 token）一律拒绝。 */
  function select(id: string): boolean {
    const p = providers.value.find((x) => x.id === id)
    if (!p || !p.enabled) return false
    currentProviderId.value = id
    return true
  }

  return {
    providers, auditNumber, complianceNote, defaultProviderId, currentProviderId,
    switching, selectedId, loading, error,
    currentProvider, defaultProvider, currentCoord, enabledProviders, poiProviders,
    load, select,
  }
})
