<script setup lang="ts">
/** POI 搜索：调 /map/poi/search?q=&provider=，结果已是 WGS84，点击可直接加入待规划池。
 *  注意后端 POI 供应商白名单仅 amap / tianditu / baidu，OpenFreeMap / Mapbox 不用于搜索。
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

const providerOptions = computed(() => [
  { value: '', label: '自动（选已配置密钥）' },
  ...props.providers.map((p) => ({ value: p.id, label: p.label })),
])

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
  <div class="rounded-lg border border-border bg-card/95 p-2 shadow-sm">
    <label class="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-foreground">
      <Search class="h-3.5 w-3.5 text-primary" /> 搜索地点
    </label>
    <form class="flex items-center gap-1.5" @submit.prevent="search">
      <Input v-model="q" placeholder="关键词 / 地址" class="h-8 flex-1 text-xs" @keydown.enter.prevent="search" />
      <Button type="submit" size="sm" class="h-8 px-2.5" :disabled="loading || !q.trim()">
        <Loader2 v-if="loading" class="h-3.5 w-3.5 animate-spin" />
        <Search v-else class="h-3.5 w-3.5" />
      </Button>
    </form>
    <select
      v-if="providerOptions.length > 1"
      v-model="provider"
      class="mt-1.5 h-7 w-full rounded-md border border-input bg-card px-1.5 text-[11px] text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <option v-for="o in providerOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>

    <p v-if="error" class="mt-1.5 rounded border border-destructive/40 bg-destructive/5 px-1.5 py-1 text-[10px] text-destructive">
      {{ error }}
    </p>

    <div v-if="results.length" class="mt-2 max-h-56 space-y-1.5 overflow-y-auto pr-0.5">
      <div v-for="poi in results" :key="poi.id" class="rounded-md border border-border bg-background p-2">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-xs font-medium text-foreground">{{ poi.name }}</p>
            <p class="mt-0.5 line-clamp-1 text-[10px] text-muted-foreground">
              {{ poi.address || '暂无地址' }}
            </p>
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
          <Badge variant="outline">{{ poi.provider }}</Badge>
          <span v-if="poi.category" class="truncate">{{ poi.category }}</span>
          <span class="ml-auto flex items-center gap-0.5"><MapPin class="h-2.5 w-2.5" />{{ poi.lng.toFixed(4) }}, {{ poi.lat.toFixed(4) }}</span>
        </div>
      </div>
    </div>
    <p v-else-if="searched && !loading && !error" class="mt-2 text-center text-[10px] text-muted-foreground">
      没有匹配的地点
    </p>
  </div>
</template>
