/** 地图底图状态：脱敏 provider 列表、审图号/合规文案、当前底图与坐标系。
 *  后端 /map/providers 与 /map/config 的字段原样接入；密钥只在后端，前端 style 不含 key。
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
  complianceNote: string
  defaultProviderId: string
  providers: MapProvider[]
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
export const POI_PROVIDER_IDS = ['amap', 'tianditu', 'baidu']

/**
 * 生成传给 map.setStyle 的值：
 * - OpenFreeMap（无 tileUrlTemplate）→ 直接用其 style URL 字符串（远程矢量 style）；
 * - 国内三家 / Mapbox → 用后端返回的 raster style 对象，瓦片已是 /map/tiles/... 代理路径，不含密钥。
 */
export function styleForProvider(p: MapProvider): string | MapStyleSpec {
  if (!p.tileUrlTemplate) {
    const url = p.style?.styleUrl || p.styleUrl
    if (url) return String(url)
  }
  if (p.style && (p.style.version || p.style.sources)) return p.style
  return { version: 8, name: p.label, sources: {}, layers: [] }
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
    currentProvider, currentCoord, enabledProviders, poiProviders,
    load, select,
  }
})
