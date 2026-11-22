<script setup lang="ts">
/** 记忆页：跨行程聚合 moments，按时间倒序的瞬间流。
 *  带行程 ID 时只展示该行程的记忆（足迹页「进入行程记忆」跳转过来），否则展示全部。
 *  图片按 media_json 里的附件 ID 渲染缩略图，点击放大；可见范围由后端过滤，本页只展示返回数据。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Images, Loader2, MapPin, ArrowUpRight, Smile, X } from 'lucide-vue-next'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/common/EmptyState.vue'

interface Trip { id: string; title: string }
interface Moment {
  id: string
  content: string | null
  mood: string | null
  lng: number | null
  lat: number | null
  coord_system: string
  taken_at: string | null
  media_json: string | null
  is_public?: boolean
}
interface Memory extends Moment { tripId: string; tripTitle: string }

const route = useRoute()
const router = useRouter()
const all = ref<Memory[]>([])
const loading = ref(true)
const error = ref('')
const keyword = ref('')
const previewUrl = ref('')

/** 足迹页跳转带上行程 ID 时，聚焦单个行程的记忆。 */
const focusTripId = computed(() => String(route.params.tripId ?? route.query.trip ?? ''))
const focusTitle = ref('')

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    if (focusTripId.value) {
      const ms = await api.get<Moment[]>(`/trips/${encodeURIComponent(focusTripId.value)}/moments`)
      const title = await api.get<{ title: string }>(`/trips/${encodeURIComponent(focusTripId.value)}`).catch(() => ({ title: '该行程' }))
      focusTitle.value = title.title || '该行程'
      all.value = (ms ?? []).map((m) => ({ ...m, tripId: focusTripId.value, tripTitle: focusTitle.value }))
    } else {
      const trips = await api.get<Trip[]>('/trips?status=all')
      const groups = await Promise.all((trips ?? []).map(async (t) => {
        try {
          const ms = await api.get<Moment[]>(`/trips/${encodeURIComponent(t.id)}/moments`)
          return (ms ?? []).map((m) => ({ ...m, tripId: t.id, tripTitle: t.title }))
        } catch {
          return [] as Memory[]
        }
      }))
      all.value = groups.flat().sort((a, b) => (b.taken_at || '').localeCompare(a.taken_at || ''))
    }
  } catch (e) {
    error.value = (e as Error)?.message || '记忆加载失败'
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return all.value
  return all.value.filter((m) =>
    (m.content || '').toLowerCase().includes(k)
    || (m.mood || '').toLowerCase().includes(k)
    || m.tripTitle.toLowerCase().includes(k),
  )
})

/** 按天分组，形成时间线。 */
const days = computed(() => {
  const map = new Map<string, Memory[]>()
  for (const m of filtered.value) {
    const key = m.taken_at ? m.taken_at.slice(0, 10) : '未标注时间'
    const arr = map.get(key) ?? []
    arr.push(m)
    map.set(key, arr)
  }
  return [...map.entries()].map(([date, list]) => ({ date, list }))
})

/** media_json 为附件 ID 的 JSON 数组字符串；兼容旧的手填单值。 */
function mediaIds(m: Memory): string[] {
  if (!m.media_json) return []
  const s = m.media_json.trim()
  if (!s) return []
  try {
    const v: unknown = JSON.parse(s)
    if (Array.isArray(v)) return v.filter((x): x is string => typeof x === 'string' && Boolean(x))
    if (typeof v === 'string' && v) return [v]
  } catch {
    if (!s.startsWith('[') && !s.startsWith('{')) return [s]
  }
  return []
}
function mediaUrl(id: string): string {
  return `/api/v1/uploads/${encodeURIComponent(id)}`
}

onMounted(loadAll)
</script>

<template>
  <div class="mx-auto max-w-[820px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Images class="h-5 w-5 text-primary" /> {{ focusTripId ? `${focusTitle || '行程'}的记忆` : '记忆' }}</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">
          {{ focusTripId ? '这一程留下的片段，按时间倒序排成一条流' : '所有行程里的瞬间，按时间倒序排成一条流' }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button v-if="focusTripId" variant="outline" size="sm" @click="router.push('/memories')">查看全部记忆</Button>
        <input
          v-model="keyword"
          class="h-9 w-48 rounded-lg border border-input bg-card px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="搜索内容 / 心情 / 行程"
        />
      </div>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在汇总记忆…</div>

    <template v-else>
      <EmptyState v-if="!filtered.length" title="还没有可展示的瞬间" description="在行程的「瞬间」页记录旅途片段，这里会自动汇总。" :icon="Images">
        <button class="min-h-9 text-xs text-primary hover:underline" @click="router.push('/trips')">前往行程</button>
      </EmptyState>

      <div v-else class="space-y-6">
        <section v-for="group in days" :key="group.date">
          <div class="mb-2 flex items-center gap-2">
            <h2 class="text-xs font-semibold text-foreground">{{ formatDate(group.date) }}</h2>
            <span class="h-px flex-1 bg-border" />
            <span class="text-[10px] text-muted-foreground">{{ group.list.length }} 条</span>
          </div>
          <div class="space-y-3 border-l-2 border-border pl-4">
            <article v-for="m in group.list" :key="m.id" class="relative rounded-lg border border-border bg-card p-3.5">
              <span class="absolute -left-[21px] top-4 h-2 w-2 rounded-full bg-primary ring-4 ring-background" />
              <div class="flex items-start justify-between gap-3">
                <p class="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{{ m.content || '（无文字）' }}</p>
                <button
                  class="shrink-0 text-[11px] text-primary hover:underline"
                  @click="router.push(`/trips/${m.tripId}/moments`)"
                >{{ m.tripTitle }} <ArrowUpRight class="inline h-3 w-3" /></button>
              </div>

              <!-- 图片缩略图，点击放大 -->
              <div v-if="mediaIds(m).length" class="mt-2.5 grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
                <button
                  v-for="id in mediaIds(m)"
                  :key="id"
                  class="aspect-square overflow-hidden rounded-md border border-border bg-muted"
                  @click="previewUrl = mediaUrl(id)"
                >
                  <img :src="mediaUrl(id)" alt="瞬间图片" class="h-full w-full object-cover" />
                </button>
              </div>

              <div class="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <Badge v-if="m.mood" variant="outline"><Smile class="mr-0.5 inline h-2.5 w-2.5" />{{ m.mood }}</Badge>
                <span v-if="m.lng !== null && m.lat !== null" class="inline-flex items-center gap-0.5">
                  <MapPin class="h-3 w-3" />{{ m.lng.toFixed(4) }}, {{ m.lat.toFixed(4) }}
                </span>
                <span>{{ m.taken_at ? m.taken_at.slice(11, 16) : '' }}</span>
              </div>
            </article>
          </div>
        </section>
      </div>
    </template>

    <!-- 图片放大查看 -->
    <div v-if="previewUrl" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" @click="previewUrl = ''">
      <img :src="previewUrl" alt="瞬间图片大图" class="max-h-full max-w-full rounded-lg object-contain shadow-lg" @click.stop />
      <button class="absolute right-5 top-5 rounded-lg border border-white/40 bg-black/40 p-2 text-white" aria-label="关闭" @click="previewUrl = ''">
        <X class="h-5 w-5" />
      </button>
    </div>
  </div>
</template>
