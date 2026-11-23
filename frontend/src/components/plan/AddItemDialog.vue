<script setup lang="ts">
/** 新增条目对话框：字段对齐 PlanItemCreate；sort_key 由前端 keyBetween 追加到目标分组末尾。
 *  分类改为下拉，选项来自 GET /plan/categories 的 8 个中文预设（失败时 store 已给本地兜底）；
 *  开始 / 时长 / 结束交给 TimeField 联动，时长统一显示 2h10m，日期用所属行程日的 date 拼 ISO。
 */
import { computed, reactive, ref, watch } from 'vue'
import { Loader2, LocateFixed, Search, Link2 } from 'lucide-vue-next'
import { useToastStore } from '@/stores/toast'
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
const toast = useToastStore()

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

watch(open, (v) => {
  if (!v) return
  form.type = props.defaultType
  form.day_id = props.defaultDayId ?? ''
  linkedItemId.value = ''
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
  timeKey.value += 1
  error.value = ''
})

/** 目标分组末尾追加：保证 sort_key 始终是合法 fractional key，避免落入后端 next_sort_key 的 ...z 键。 */
function endSortKey(): string {
  const targetKey = form.day_id || POOL_KEY
  const existing = dnd.lists[targetKey] ?? []
  const last = existing.length ? existing[existing.length - 1].sort_key : null
  return keyBetween(last, null)
}

const locating = ref(false)
const locationMessage = ref('')
const linkedItemId = ref('')
const existingPlaceOptions = computed(() => [
  { value: '', label: '不关联' },
  ...plan.allItems.filter((item) => item.type === 'place' && typeof item.lng === 'number' && typeof item.lat === 'number')
    .map((item) => ({ value: item.id, label: item.title })),
])
function linkExistingPlace(id: string) {
  linkedItemId.value = id
  const item = plan.allItems.find((candidate) => candidate.id === id)
  if (!item) return
  form.title = item.title
  form.subtitle = item.subtitle ?? ''
  form.address = item.address ?? ''
  form.lng = item.lng ?? null
  form.lat = item.lat ?? null
  form.coord_system = item.coord_system ?? 'WGS84'
  locationMessage.value = '已关联行程中的地点'
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
  <Dialog v-model="open" title="添加条目" description="可指定类型与归属天；不指定则进入待规划池">
    <form class="space-y-3" @submit.prevent="submit">
      <div class="grid grid-cols-2 gap-3">
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
        <label class="flex items-center gap-1 text-xs font-medium"><Link2 class="size-3.5" />关联已有地点</label>
        <Select :model-value="linkedItemId" :options="existingPlaceOptions" @update:model-value="linkExistingPlace" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">标题 <span class="text-destructive">*</span></label>
        <Input v-model="form.title" placeholder="例如：灵隐寺" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">副标题</label>
        <Input v-model="form.subtitle" placeholder="可选" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">地址</label>
        <div class="flex gap-1.5"><Input v-model="form.address" placeholder="输入地址后可搜索坐标" /><Button type="button" variant="outline" size="sm" :disabled="locating" @click="geocodeAddress"><Search class="h-3.5 w-3.5" /> 搜索</Button><Button type="button" variant="outline" size="sm" :disabled="locating" title="使用当前位置" @click="useCurrentLocation"><LocateFixed class="h-3.5 w-3.5" /></Button></div>
        <p class="text-[10px] text-muted-foreground">{{ locationMessage || (form.lng !== null && form.lat !== null ? '地点坐标已自动填入' : '搜索地址或使用当前位置后自动填入坐标') }}</p>
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">分类</label>
        <Select v-model="form.category" :options="categoryOptions" />
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
      <div v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">{{ error }}</div>
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
