<script setup lang="ts">
/**
 * 添加地点 / 活动对话框（TREK 风格两栏布局）。
 *  - 左栏：搜索框 + POI 搜索结果（点击即回填名称 / 地址 / 坐标），下方是详情表单；
 *  - 右栏：行程中已保存的地点列表（可直接复用），以及常用地点快捷入口；
 *  - 顶部一行放类型与归属天，底部固定「添加 / 取消」。
 */
import { computed, reactive, ref, watch } from 'vue'
import { Loader2, LocateFixed, Search, Star, MapPin, Plus } from 'lucide-vue-next'
import { ApiError, api } from '@/lib/api'
import { keyBetween } from '@/lib/sortKey'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import TimeField from './TimeField.vue'
import { POOL_KEY, usePlanContext } from '@/composables/usePlanDnd'
import { usePlanStore } from '@/stores/plan'
import type { PlanItemCreate, PlanType } from '@/stores/plan'

const props = withDefaults(
  defineProps<{ defaultType?: PlanType; defaultDayId?: string | null }>(),
  { defaultType: 'place', defaultDayId: null },
)
const open = defineModel<boolean>({ default: false })
const { dnd } = usePlanContext()
const plan = usePlanStore()

/** 对齐后端 poi_adapter 的输出（坐标已归一化为 WGS84）。 */
interface Poi {
  id: string
  name: string
  address: string
  lng: number
  lat: number
  category: string
  provider: string
}

const form = reactive({
  type: 'place' as string,
  title: '',
  subtitle: '',
  address: '',
  lng: null as number | null,
  lat: null as number | null,
  coord_system: 'WGS84',
  category: '',
  day_id: '',
  note: '',
  startTime: null as string | null,
  endTime: null as string | null,
  durationMin: null as number | null,
})
const timeKey = ref(0)
const saving = ref(false)
const error = ref('')

/** POI 搜索 */
const keyword = ref('')
const searching = ref(false)
const searchError = ref('')
const results = ref<Poi[]>([])
const searched = ref(false)
let searchVersion = 0

const typeOptions = [
  { value: 'place', label: '地点' },
  { value: 'activity', label: '活动' },
  { value: 'hotel', label: '酒店' },
  { value: 'transport', label: '交通' },
  { value: 'note', label: '备注' },
]
const dayOptions = computed(() => [
  { value: '', label: '待规划池' },
  ...dnd.days.value.map((d) => ({
    value: d.id,
    label: `第 ${d.day_index} 天${d.date ? ` · ${d.date}` : ''}`,
  })),
])

/** 分类下拉：8 个中文预设 + 「其他」兜底 + 「未分类」；旧值不在预设里时也保留一个同名选项。 */
const categoryOptions = computed(() => {
  const list = plan.categories.map((c) => ({ value: c.id, label: c.label }))
  if (!list.some((o) => o.value === '其他')) list.push({ value: '其他', label: '其他' })
  if (form.category && !list.some((o) => o.value === form.category)) {
    list.unshift({ value: form.category, label: form.category })
  }
  return [{ value: '', label: '未分类' }, ...list]
})

/** 时间 ISO 用所属行程日的 date 拼接；待规划池没有日期时由后端 normalize_times 兜底。 */
const dayDate = computed(() => {
  if (!form.day_id) return null
  return dnd.days.value.find((d) => d.id === form.day_id)?.date ?? null
})

/** 行程中已保存的地点（右栏「已保存地点」），按加入顺序倒序展示最近使用的。 */
const savedPlaces = computed(() =>
  plan.allItems
    .filter((item) => item.type === 'place' && typeof item.lng === 'number' && typeof item.lat === 'number')
    .slice()
    .reverse()
    .slice(0, 30),
)

const locating = ref(false)
const locationMessage = ref('')

watch(open, (v) => {
  if (!v) {
    searchVersion += 1
    searching.value = false
    return
  }
  searchVersion += 1
  form.type = props.defaultType
  form.day_id = props.defaultDayId ?? ''
  form.title = ''
  form.subtitle = ''
  form.address = ''
  form.lng = null
  form.lat = null
  form.coord_system = 'WGS84'
  form.category = ''
  form.note = ''
  form.startTime = null
  form.endTime = null
  form.durationMin = null
  keyword.value = ''
  results.value = []
  searched.value = false
  searchError.value = ''
  timeKey.value += 1
  error.value = ''
  locationMessage.value = ''
})

/** 目标分组末尾追加：保证 sort_key 始终是合法 fractional key，避免落入后端 next_sort_key 的 ...z 键。 */
function endSortKey(): string {
  const targetKey = form.day_id || POOL_KEY
  const existing = dnd.lists[targetKey] ?? []
  const last = existing.length ? existing[existing.length - 1].sort_key : null
  return keyBetween(last, null)
}

/** POI 搜索：结果直接可点，回填名称 / 地址 / 坐标 / 分类。 */
async function searchPoi() {
  const q = keyword.value.trim()
  if (!q) return
  const version = ++searchVersion
  searching.value = true
  searchError.value = ''
  searched.value = true
  try {
    const params = new URLSearchParams({ q })
    const found = await api.get<Poi[]>(`/map/poi/search?${params.toString()}`)
    if (version === searchVersion) results.value = found
  } catch (e) {
    if (version !== searchVersion) return
    searchError.value = e instanceof ApiError ? e.message : (e as Error).message
    results.value = []
  } finally {
    if (version === searchVersion) searching.value = false
  }
}

/** 关键词清空时立即收起结果面板，避免出现「删完仍显示结果」的僵硬感。 */
watch(keyword, (v) => {
  searchVersion += 1
  results.value = []
  searched.value = false
  searchError.value = ''
  searching.value = false
  if (v.trim()) return
})

function pickPoi(poi: Poi) {
  form.title = poi.name
  form.address = poi.address || ''
  form.lng = poi.lng
  form.lat = poi.lat
  form.coord_system = 'WGS84'
  if (poi.category) form.category = poi.category
  locationMessage.value = '已选择该地点'
}

/** 复用行程中已保存的地点：只回填地点信息，不改类型与归属天。 */
function pickSavedPlace(item: PlanItemCreate & { id: string }) {
  form.title = item.title
  form.subtitle = item.subtitle ?? ''
  form.address = item.address ?? ''
  form.lng = item.lng ?? null
  form.lat = item.lat ?? null
  form.coord_system = item.coord_system ?? 'WGS84'
  locationMessage.value = '已复用行程中的地点'
}

async function geocodeAddress() {
  if (!form.address.trim() || locating.value) return
  locating.value = true
  locationMessage.value = ''
  try {
    const result = await api.get<{ lng: number; lat: number; coord_system: string }>(`/map/geocode?address=${encodeURIComponent(form.address.trim())}`)
    form.lng = result.lng
    form.lat = result.lat
    form.coord_system = result.coord_system || 'WGS84'
    locationMessage.value = '已根据地址填入坐标'
  } catch (e) {
    locationMessage.value = (e as Error).message || '地址搜索失败'
  } finally {
    locating.value = false
  }
}

async function useCurrentLocation() {
  if (!navigator.geolocation) { locationMessage.value = '此设备不支持定位'; return }
  locating.value = true
  locationMessage.value = ''
  navigator.geolocation.getCurrentPosition((position) => {
    form.lng = position.coords.longitude
    form.lat = position.coords.latitude
    form.coord_system = 'WGS84'
    locationMessage.value = '已使用当前位置'
    locating.value = false
  }, (e) => {
    locationMessage.value = e.message || '无法获取当前位置'
    locating.value = false
  }, { enableHighAccuracy: true, timeout: 10000 })
}

async function submit() {
  if (!form.title.trim()) {
    error.value = '请填写标题'
    return
  }
  error.value = ''
  saving.value = true
  let sortKey: string
  try {
    sortKey = endSortKey()
  } catch (e) {
    error.value = `排序键计算失败：${(e as Error).message}，请刷新后重试`
    saving.value = false
    return
  }
  const payload: PlanItemCreate = {
    day_id: form.day_id || null,
    bucket: 'main',
    type: form.type as PlanType,
    title: form.title.trim(),
    subtitle: form.subtitle.trim() || null,
    address: form.address.trim() || null,
    lng: form.lng,
    lat: form.lat,
    coord_system: form.coord_system,
    category: form.category || null,
    start_time: form.startTime,
    end_time: form.endTime,
    duration_min: form.durationMin,
    note: form.note.trim() || null,
    source: 'manual',
    sort_key: sortKey,
  }
  try {
    await dnd.addItem(payload)
    open.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog v-model="open" title="添加地点 / 活动" description="搜索地点或直接填写；可复用行程中已保存的地点" width="max-w-4xl">
    <form class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]" @submit.prevent="submit">
      <!-- 左栏：搜索 + 详情 -->
      <div class="min-w-0 space-y-3">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">搜索地点</label>
          <div class="flex gap-1.5">
            <Input
              v-model="keyword"
              placeholder="输入关键词搜索地点，如：拙政园"
              @keydown.enter.prevent="searchPoi"
            />
            <Button type="button" variant="outline" size="sm" :disabled="searching || !keyword.trim()" @click="searchPoi">
              <Loader2 v-if="searching" class="h-3.5 w-3.5 animate-spin" />
              <Search v-else class="h-3.5 w-3.5" /> 搜索
            </Button>
          </div>
        </div>

        <!-- 搜索结果：点选即回填 -->
        <div
          v-if="results.length || searchError || (searched && !searching && !results.length)"
          class="max-h-44 overflow-y-auto rounded-lg border border-border bg-muted/30 p-1.5"
        >
          <p v-if="searchError" class="rounded border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-[11px] text-destructive">
            {{ searchError }}
          </p>
          <p v-else-if="searched && !searching && !results.length" class="py-3 text-center text-[11px] text-muted-foreground">
            没有匹配的地点
          </p>
          <button
            v-for="poi in results"
            :key="poi.id"
            type="button"
            class="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-card"
            @click="pickPoi(poi)"
          >
            <MapPin class="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-xs font-medium text-foreground">{{ poi.name }}</span>
              <span class="block truncate text-[10px] text-muted-foreground">{{ poi.address || '暂无地址' }}</span>
            </span>
            <span class="shrink-0 text-[10px] tabular-nums text-muted-foreground">
              {{ poi.lng.toFixed(4) }}, {{ poi.lat.toFixed(4) }}
            </span>
          </button>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <label class="text-xs font-medium">类型</label>
            <Select v-model="form.type" :options="typeOptions" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium">归属</label>
            <Select v-model="form.day_id" :options="dayOptions" />
          </div>
        </div>

        <div class="space-y-1.5">
          <label class="text-xs font-medium">标题 <span class="text-destructive">*</span></label>
          <Input v-model="form.title" placeholder="例如：拙政园" />
        </div>

        <div class="space-y-1.5">
          <label class="text-xs font-medium">地址</label>
          <div class="flex gap-1.5">
            <Input v-model="form.address" placeholder="输入地址后可搜索坐标" />
            <Button type="button" variant="outline" size="sm" :disabled="locating" title="按地址搜索坐标" @click="geocodeAddress">
              <Search class="h-3.5 w-3.5" />
            </Button>
            <Button type="button" variant="outline" size="sm" :disabled="locating" title="使用当前位置" @click="useCurrentLocation">
              <LocateFixed class="h-3.5 w-3.5" />
            </Button>
          </div>
          <p class="text-[10px] text-muted-foreground">
            {{ locationMessage || (form.lng !== null && form.lat !== null
              ? `坐标已填入：${form.lng.toFixed(4)}, ${form.lat.toFixed(4)}`
              : '搜索地址或使用当前位置后自动填入坐标') }}
          </p>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <label class="text-xs font-medium">分类</label>
            <Select v-model="form.category" :options="categoryOptions" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium">副标题</label>
            <Input v-model="form.subtitle" placeholder="可选" />
          </div>
        </div>

        <div class="space-y-1.5">
          <label class="text-xs font-medium">开始 / 时长 / 结束</label>
          <TimeField
            :key="timeKey"
            v-model:startTime="form.startTime"
            v-model:endTime="form.endTime"
            v-model:durationMin="form.durationMin"
            :date="dayDate"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-xs font-medium">备注</label>
          <Input v-model="form.note" placeholder="可选" />
        </div>

        <div v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">
          {{ error }}
        </div>
      </div>

      <!-- 右栏：已保存地点 -->
      <aside class="min-w-0 space-y-2 rounded-lg border border-border bg-muted/30 p-3">
        <div class="flex items-center gap-1.5">
          <Star class="h-3.5 w-3.5 text-primary" />
          <span class="text-xs font-medium">已保存地点</span>
          <span class="ml-auto text-[10px] tabular-nums text-muted-foreground">{{ savedPlaces.length }}</span>
        </div>
        <p v-if="!savedPlaces.length" class="py-4 text-center text-[11px] leading-relaxed text-muted-foreground">
          行程中还没有已定位的地点。<br />搜索后添加即可在此复用。
        </p>
        <ul v-else class="max-h-72 space-y-1 overflow-y-auto">
          <li v-for="item in savedPlaces" :key="item.id">
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-card"
              @click="pickSavedPlace(item)"
            >
              <MapPin class="h-3 w-3 shrink-0 text-muted-foreground" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[11px] font-medium text-foreground">{{ item.title }}</span>
                <span class="block truncate text-[10px] text-muted-foreground">{{ item.address || item.subtitle || '已定位地点' }}</span>
              </span>
              <Plus class="h-3 w-3 shrink-0 text-primary" />
            </button>
          </li>
        </ul>
      </aside>
    </form>
    <template #footer>
      <Button variant="outline" size="sm" :disabled="saving" @click="open = false">取消</Button>
      <Button size="sm" :disabled="saving" @click="submit">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        {{ saving ? '添加中…' : '添加' }}
      </Button>
    </template>
  </Dialog>
</template>
