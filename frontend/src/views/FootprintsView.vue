<script setup lang="ts">
/** 足迹页：跨行程聚合 moments 中带坐标的点，用小型地图 + 坐标列表展示。
 *  后端无全局瞬间端点，故先取 /trips?status=all，再逐行程取 /trips/{id}/moments 聚合。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Footprints, MapPin, Loader2, ArrowUpRight } from 'lucide-vue-next'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import MapPane from '@/components/map/MapPane.vue'

interface Trip { id: string; title: string }
interface Moment {
  id: string
  content: string | null
  mood: string | null
  lng: number | null
  lat: number | null
  coord_system: string
  taken_at: string | null
}
interface Footprint extends Moment { tripId: string; tripTitle: string }

const router = useRouter()
const all = ref<Footprint[]>([])
const loading = ref(true)
const error = ref('')

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const trips = await api.get<Trip[]>('/trips?status=all')
    const groups = await Promise.all((trips ?? []).map(async (t) => {
      try {
        const ms = await api.get<Moment[]>(`/trips/${encodeURIComponent(t.id)}/moments`)
        return (ms ?? []).map((m) => ({ ...m, tripId: t.id, tripTitle: t.title }))
      } catch {
        return [] as Footprint[] // 无权限或行程无瞬间时跳过，不影响其它行程
      }
    }))
    all.value = groups.flat()
  } catch (e) {
    error.value = (e as Error)?.message || '足迹加载失败'
  } finally {
    loading.value = false
  }
}

const geocoded = computed(() =>
  all.value.filter((m) => typeof m.lng === 'number' && typeof m.lat === 'number')
    .sort((a, b) => (b.taken_at || '').localeCompare(a.taken_at || '')),
)

/** 复用 MapPane 的精简点数据（WGS84，由 MapPane 按当前底图反转换）。 */
const mapPoints = computed(() => geocoded.value.map((m) => ({
  id: m.id,
  lng: m.lng,
  lat: m.lat,
  title: m.content || m.tripTitle,
  type: 'moment',
})))

onMounted(loadAll)
</script>

<template>
  <div class="mx-auto max-w-[1200px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Footprints class="h-5 w-5 text-primary" /> 足迹</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">
          已定位 {{ geocoded.length }} 个点 · 共 {{ all.length }} 条瞬间
        </p>
      </div>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在汇总足迹…</div>

    <template v-else>
      <EmptyState v-if="!geocoded.length" title="还没有带坐标的足迹" description="在行程的「瞬间」里记录内容并填写经纬度，这里就会点亮地图。" :icon="Footprints">
        <button class="text-xs text-primary hover:underline" @click="router.push('/trips')">前往行程</button>
      </EmptyState>
      <template v-else>
        <div class="h-[380px] overflow-hidden rounded-lg border border-border">
          <MapPane :items="mapPoints" :show-tools="false" />
        </div>

        <Card :padded="false">
          <h2 class="border-b border-border px-4 py-2.5 text-sm font-semibold">坐标列表</h2>
          <div class="max-h-[360px] overflow-y-auto">
            <table class="w-full text-left text-xs">
              <thead class="sticky top-0 border-b border-border bg-card text-muted-foreground">
                <tr>
                  <th class="px-4 py-2 font-medium">瞬间</th>
                  <th class="px-4 py-2 font-medium">行程</th>
                  <th class="px-4 py-2 font-medium">坐标（WGS84）</th>
                  <th class="px-4 py-2 font-medium">时间</th>
                  <th class="px-4 py-2" />
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr v-for="m in geocoded" :key="m.id" class="hover:bg-muted/40">
                  <td class="max-w-[280px] px-4 py-2">
                    <span class="block truncate text-foreground">{{ m.content || '（无文字）' }}</span>
                    <span v-if="m.mood" class="text-[10px] text-muted-foreground">{{ m.mood }}</span>
                  </td>
                  <td class="px-4 py-2 text-muted-foreground">{{ m.tripTitle }}</td>
                  <td class="px-4 py-2 font-mono text-[11px] text-foreground">
                    <span class="inline-flex items-center gap-1"><MapPin class="h-3 w-3 text-primary" />{{ m.lng?.toFixed(4) }}, {{ m.lat?.toFixed(4) }}</span>
                  </td>
                  <td class="px-4 py-2 text-muted-foreground">{{ formatDate(m.taken_at) }}</td>
                  <td class="px-4 py-2 text-right">
                    <button
                      class="inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline"
                      @click="router.push(`/trips/${m.tripId}/moments`)"
                    >查看 <ArrowUpRight class="h-3 w-3" /></button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      </template>
    </template>
  </div>
</template>
