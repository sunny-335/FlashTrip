<script setup lang="ts">
/** POI 搜索：调 /map/poi/search?q=&provider=，结果已是 WGS84，点击后走真实新增 API 加入待规划池。
 *  紧凑单行输入框，结果以绝对定位浮层下拉展示，不铺满遮挡地图。
 *  后端 POI 供应商白名单仅高德 / 天地图；底图供应商不自动成为 POI 搜索源。
 */
import { computed, ref } from 'vue'
import { Search, Loader2, Plus, MapPin } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import type { MapProvider } from '@/stores/map'
import type { PlanItem } from '@/stores/plan'
import Input from '@/components/ui/Input.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'

const props = withDefaults(
  defineProps<{ tripId: string; providers?: MapProvider[] }>(),
  { providers: () => [] },
)
const emit = defineEmits<{ added: [item: PlanItem] }>()

/** 对齐 poi_adapter._normalize 的输出。 */
interface Poi {
  id: string
  name: string
  address: string
  lng: number
  lat: number
  coord_system: string
  source_coord_system?: string
  category: string
  provider: string
}

const q = ref('')
const provider = ref('')
const results = ref<Poi[]>([])
const loading = ref(false)
const addingId = ref('')
const error = ref('')
const searched = ref(false)

/** 结果里的 provider 是供应商 id，展示时转成品牌名（品牌名保留原样）。 */
const PROVIDER_LABEL: Record<string, string> = {
  amap: '高德地图', tianditu: '天地图',
}

const providerOptions = computed(() => [
  { value: '', label: '自动选择' },
  ...props.providers.map((p) => ({ value: p.id, label: p.label })),
])

/** 结果浮层：有结果 / 出错 / 搜索无结果时才向下展开。 */
const showPanel = computed(() =>
  results.value.length > 0
  || Boolean(error.value)
  || (searched.value && !loading.value && results.value.length === 0 && !error.value),
)

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}

async function search() {
  const keyword = q.value.trim()
  if (!keyword || loading.value) return
  loading.value = true
  error.value = ''
  searched.value = true
  try {
    const params = new URLSearchParams({ q: keyword })
    if (provider.value) params.set('provider', provider.value)
    results.value = await api.get<Poi[]>(`/map/poi/search?${params.toString()}`)
  } catch (e) {
    error.value = messageOf(e)
    results.value = []
  } finally {
    loading.value = false
  }
}

/** 归一化 POI → PlanItemCreate；坐标按后端约定已是 WGS84，直接入库。 */
async function addToPool(poi: Poi) {
  if (addingId.value) return
  addingId.value = poi.id
  error.value = ''
  try {
    const item = await api.post<PlanItem>(`/trips/${props.tripId}/plan/items`, {
      title: poi.name,
      type: 'place',
      subtitle: poi.provider,
      address: poi.address,
      category: poi.category,
      lng: poi.lng,
      lat: poi.lat,
      coord_system: 'WGS84',
      source: 'poi',
      external_id: poi.id,
      day_id: null,
    })
    emit('added', item)
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    addingId.value = ''
  }
}
</script>

<template>
  <div class="relative w-full">
    <form class="flex items-center gap-1.5 rounded-lg border border-border bg-card/95 p-1.5 shadow-sm" @submit.prevent="search">
      <select
        v-if="providerOptions.length > 1"
        v-model="provider"
        class="h-8 w-24 shrink-0 rounded-md border border-input bg-card px-1.5 text-[11px] text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-label="搜索服务"
      >
        <option v-for="o in providerOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <Input v-model="q" placeholder="搜索地点" class="h-8 flex-1 text-xs" @keydown.enter.prevent="search" />
      <Button type="submit" size="sm" class="h-8 shrink-0 px-2.5 text-xs" :disabled="loading || !q.trim()">
        <Loader2 v-if="loading" class="h-3.5 w-3.5 animate-spin" />
        <Search v-else class="h-3.5 w-3.5" />
        搜索
      </Button>
    </form>

    <!-- 绝对定位浮层：不占据地图主体空间，仅在有内容时向下展开 -->
    <div
      v-if="showPanel"
      class="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-y-auto rounded-lg border border-border bg-card p-2 shadow-md"
    >
      <p v-if="error" class="rounded border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-[11px] text-destructive">
        {{ error }}
      </p>
      <p v-else-if="searched && !loading && !results.length" class="py-2 text-center text-[11px] text-muted-foreground">
        没有匹配的地点
      </p>
      <div v-else class="space-y-1.5">
        <div v-for="poi in results" :key="poi.id" class="rounded-md border border-border bg-background p-2">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate text-xs font-medium text-foreground">{{ poi.name }}</p>
              <p class="mt-0.5 line-clamp-1 text-[10px] text-muted-foreground">{{ poi.address || '暂无地址' }}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              class="h-7 shrink-0 px-2 text-[10px]"
              :disabled="addingId === poi.id"
              @click="addToPool(poi)"
            >
              <Loader2 v-if="addingId === poi.id" class="h-3 w-3 animate-spin" />
              <Plus v-else class="h-3 w-3" /> 加入
            </Button>
          </div>
          <div class="mt-1 flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
            <Badge variant="outline">{{ PROVIDER_LABEL[poi.provider] ?? poi.provider }}</Badge>
            <span v-if="poi.category" class="truncate">{{ poi.category }}</span>
            <span class="ml-auto flex items-center gap-0.5"><MapPin class="h-2.5 w-2.5" />{{ poi.lng.toFixed(4) }}, {{ poi.lat.toFixed(4) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
