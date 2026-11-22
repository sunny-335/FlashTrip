<script setup lang="ts">
/** 完整修改弹窗：点击规划池 / 待规划池的地点卡片即可打开。
 *  字段覆盖 PlanItem 全部可编辑项；保存走 PUT /trips/{id}/plan/items/{item_id}，
 *  删除走 DELETE 并用「是 / 否」二次确认；成功后刷新 plan 与冲突。
 *  开始 / 时长 / 结束交给 TimeField 联动，时长统一显示 2h10m。
 */
import { computed, reactive, ref, watch } from 'vue'
import { Loader2, Trash2, Save, AlertTriangle } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import { keyBetween } from '@/lib/sortKey'
import { formatDate } from '@/lib/utils'
import { findLocalConflicts } from '@/lib/time'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import TimeField from './TimeField.vue'
import { POOL_KEY, usePlanContext } from '@/composables/usePlanDnd'
import { usePlanStore, type PlanItem, type PlanItemPatch, type PlanType } from '@/stores/plan'

const props = defineProps<{ item: PlanItem | null }>()
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [] }>()
const { dnd } = usePlanContext()
const store = usePlanStore()

const TYPE_OPTIONS = [
  { value: 'place', label: '地点' },
  { value: 'hotel', label: '酒店' },
  { value: 'transport', label: '交通' },
  { value: 'activity', label: '活动' },
  { value: 'note', label: '备注' },
]
const COORD_OPTIONS = [
  { value: 'WGS84', label: 'WGS84（全球定位）' },
  { value: 'GCJ-02', label: 'GCJ-02（高德 / 腾讯）' },
  { value: 'BD-09', label: 'BD-09（百度）' },
  { value: 'CGCS2000', label: 'CGCS2000（天地图）' },
]

const form = reactive({
  title: '',
  subtitle: '',
  type: 'place',
  day_id: '' as string,
  address: '',
  category: '',
  lng: '' as string,
  lat: '' as string,
  coord_system: 'WGS84',
  note: '',
  startTime: null as string | null,
  endTime: null as string | null,
  durationMin: null as number | null,
})
const timeKey = ref(0)
const saving = ref(false)
const deleting = ref(false)
const error = ref('')
const confirmOpen = ref(false)

/** 所属行程日：空串表示「待规划」（day_id=null）。 */
const dayOptions = computed(() => [
  { value: '', label: '待规划' },
  ...dnd.days.value.map((d) => ({
    value: d.id,
    label: `第 ${d.day_index} 天${d.date ? ` · ${formatDate(d.date)}` : ''}`,
  })),
])

/** 分类：接口预设优先（失败时 store 已给本地 8 预设），并保留「其他」兜底与「未分类」。 */
const categoryOptions = computed(() => {
  const list = store.categories.map((c) => ({ value: c.id, label: c.label }))
  if (!list.some((o) => o.value === '其他')) list.push({ value: '其他', label: '其他' })
  if (form.category && !list.some((o) => o.value === form.category)) {
    list.unshift({ value: form.category, label: form.category })
  }
  return [{ value: '', label: '未分类' }, ...list]
})

/** 坐标体系：选中值不在预设里时补一个同名选项，避免下拉空白。 */
const coordOptions = computed(() => {
  const list = [...COORD_OPTIONS]
  if (form.coord_system && !list.some((o) => o.value === form.coord_system)) {
    list.push({ value: form.coord_system, label: form.coord_system })
  }
  return list
})

/** 时间 ISO 用所属行程日的 date 拼接；待规划时用空日期，后端 normalize_times 兜底。 */
const dayDate = computed(() => {
  if (!form.day_id) return null
  return dnd.days.value.find((d) => d.id === form.day_id)?.date ?? null
})

/** 本地即时冲突提示：按「前项结束严格晚于后项开始」判定，14:00 结束 / 14:00 开始不冲突。 */
const localConflictHint = computed(() => {
  if (!form.day_id || !form.startTime || !form.endTime || !props.item) return ''
  const virtual: PlanItem = { ...props.item, day_id: form.day_id, start_time: form.startTime, end_time: form.endTime }
  const others = [...store.planned, ...store.unplanned].filter((i) => i.id !== props.item!.id)
  const hits = findLocalConflicts([...others, virtual])
  return hits.some((c) => c.itemId === virtual.id || c.withItemId === virtual.id)
    ? '当前时间与同日其他行程重叠，保存后可点击时间进行重排。'
    : ''
})

function fill(item: PlanItem): void {
  form.title = item.title ?? ''
  form.subtitle = item.subtitle ?? ''
  form.type = item.type || 'place'
  form.day_id = item.day_id ?? ''
  form.address = item.address ?? ''
  form.category = item.category ?? ''
  form.lng = item.lng == null ? '' : String(item.lng)
  form.lat = item.lat == null ? '' : String(item.lat)
  form.coord_system = item.coord_system || 'WGS84'
  form.note = item.note ?? ''
  form.startTime = item.start_time ?? null
  form.endTime = item.end_time ?? null
  form.durationMin = item.duration_min ?? null
  error.value = ''
  timeKey.value += 1
}

watch([open, () => props.item?.id], () => {
  if (open.value && props.item) fill(props.item)
}, { immediate: true })

function toNumber(v: string): number | null {
  const t = v.trim()
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

function buildPatch(): PlanItemPatch {
  return {
    title: form.title.trim(),
    subtitle: form.subtitle.trim() || null,
    type: form.type as PlanType,
    day_id: form.day_id || null,
    address: form.address.trim() || null,
    category: form.category || null,
    lng: toNumber(form.lng),
    lat: toNumber(form.lat),
    coord_system: form.coord_system,
    note: form.note.trim() || null,
    start_time: form.startTime,
    end_time: form.endTime,
    duration_min: form.durationMin,
  }
}

async function save(): Promise<void> {
  if (!props.item) return
  if (!form.title.trim()) {
    error.value = '请填写标题'
    return
  }
  // 结束早于开始的错误码 1001 由后端 normalize_times 校验，前端用 ApiError.message 透出中文提示
  error.value = ''
  saving.value = true
  try {
    const patch = buildPatch()
    // 换到别的行程日 / 待规划池时，补一个目标分组末尾的排序键，避免落点异常
    if ((form.day_id || null) !== props.item.day_id) {
      const targetKey = form.day_id || POOL_KEY
      const list = (dnd.lists[targetKey] ?? []).filter((i) => i.id !== props.item!.id)
      const last = list.length ? list[list.length - 1].sort_key : null
      patch.sort_key = keyBetween(last, null)
    }
    await dnd.updateItem(props.item.id, patch)
    await dnd.reload()
    emit('saved')
    open.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    saving.value = false
  }
}

async function doDelete(): Promise<void> {
  if (!props.item) return
  confirmOpen.value = false
  deleting.value = true
  error.value = ''
  try {
    await dnd.deleteItem(props.item.id)
    await dnd.reload()
    emit('saved')
    open.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <Dialog v-model="open" title="修改行程条目" description="可调整归属、分类、时间与坐标；改开始或时长会自动算结束" width="max-w-lg">
    <form v-if="item" class="space-y-3" @submit.prevent="save">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">标题 <span class="text-destructive">*</span></label>
          <Input v-model="form.title" placeholder="例如：灵隐寺" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">副标题</label>
          <Input v-model="form.subtitle" placeholder="可选" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">类型</label>
          <Select v-model="form.type" :options="TYPE_OPTIONS" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">所属行程日</label>
          <Select v-model="form.day_id" :options="dayOptions" />
        </div>
      </div>

      <div class="space-y-1.5">
        <label class="text-xs font-medium">地址</label>
        <Input v-model="form.address" placeholder="可选" />
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">分类</label>
          <Select v-model="form.category" :options="categoryOptions" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">坐标体系</label>
          <Select v-model="form.coord_system" :options="coordOptions" />
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

      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">经度</label>
          <Input v-model="form.lng" type="number" step="any" placeholder="可选" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">纬度</label>
          <Input v-model="form.lat" type="number" step="any" placeholder="可选" />
        </div>
      </div>

      <div class="space-y-1.5">
        <label class="text-xs font-medium">备注</label>
        <textarea
          v-model="form.note"
          rows="2"
          class="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm outline-none transition placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="可选"
        />
      </div>

      <p v-if="localConflictHint" class="flex items-start gap-1.5 rounded-lg border border-amber-300/60 bg-amber-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-700">
        <AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" /> {{ localConflictHint }}
      </p>
      <div v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">{{ error }}</div>
    </form>

    <template #footer>
      <Button variant="ghost" size="sm" class="mr-auto text-destructive hover:bg-destructive/10 hover:text-destructive" :disabled="saving || deleting" @click="confirmOpen = true">
        <Trash2 class="h-3.5 w-3.5" /> 删除
      </Button>
      <Button variant="outline" size="sm" :disabled="saving || deleting" @click="open = false">取消</Button>
      <Button size="sm" :disabled="saving || deleting" @click="save">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        <Save v-else class="h-3.5 w-3.5" />
        {{ saving ? '保存中…' : '保存' }}
      </Button>
    </template>
  </Dialog>

  <ConfirmDialog
    v-model="confirmOpen"
    title="删除条目"
    :message="`确定删除「${item?.title ?? ''}」吗？删除后不可在本页恢复。`"
    confirm-text="是"
    cancel-text="否"
    danger
    :busy="deleting"
    @confirm="doDelete"
  />
</template>
