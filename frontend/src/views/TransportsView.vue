<script setup lang="ts">
/** 交通页：/trips/{id}/transports 标准 CRUD；坐标恒定 WGS84 坐标系入库。
 *  支持关联「所属行程日 / 关联地点」，列表可按 day_id 筛选。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Route, Plus, Trash2, Pencil, Loader2, MapPin, CalendarDays } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { formatDate, formatMoney } from '@/lib/utils'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

interface Transport {
  id: string
  mode: string
  from_name: string | null
  to_name: string | null
  from_lng: number | null
  from_lat: number | null
  to_lng: number | null
  to_lat: number | null
  coord_system: string
  depart_at: string | null
  arrive_at: string | null
  carrier: string | null
  seat: string | null
  price: number | null
  sort_key: string
  day_id: string | null
  plan_item_id: string | null
}

/** 行程日与计划项下拉数据，来自 GET /trips/{id}/plan/options。 */
interface PlanDay { id: string; day_index: number; date: string | null; title: string | null }
interface PlanItem { id: string; title: string | null; type: string | null; day_id: string | null }
interface PlanOptions { days: PlanDay[]; items: PlanItem[] }

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/transports`)
const items = ref<Transport[]>([])
const loading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const deleteTarget = ref<Transport | null>(null)
const deleting = ref(false)

const planOptions = ref<PlanOptions>({ days: [], items: [] })
const dayFilter = ref('')

const modeOptions = [
  { value: 'flight', label: '飞机' }, { value: 'train', label: '火车 / 高铁' },
  { value: 'car', label: '自驾' }, { value: 'bus', label: '大巴' },
  { value: 'ferry', label: '轮渡' }, { value: 'walk', label: '步行' },
  { value: 'other', label: '其他' },
]
const modeLabel = (v: string) => modeOptions.find((o) => o.value === v)?.label ?? v

/** 表单下拉：首项为「不关联」，其值为空串，提交时转 null。 */
const daySelectOptions = computed(() => [
  { value: '', label: '不关联行程日' },
  ...planOptions.value.days.map((d) => ({
    value: d.id,
    label: `第 ${d.day_index} 天${d.title ? ' · ' + d.title : ''}${d.date ? '（' + d.date + '）' : ''}`,
  })),
])
const itemSelectOptions = computed(() => [
  { value: '', label: '不关联地点' },
  ...planOptions.value.items.map((i) => ({
    value: i.id,
    label: `${i.title || '未命名地点'}${i.day_id ? '' : ' · 待规划'}`,
  })),
])
/** 筛选下拉：首项为「全部」。 */
const dayFilterOptions = computed(() => [
  { value: '', label: '全部行程日' },
  ...planOptions.value.days.map((d) => ({
    value: d.id,
    label: `第 ${d.day_index} 天${d.title ? ' · ' + d.title : ''}`,
  })),
])
function dayName(id: string | null): string {
  if (!id) return ''
  const d = planOptions.value.days.find((x) => x.id === id)
  return d ? `第 ${d.day_index} 天${d.title ? ' · ' + d.title : ''}` : ''
}
function itemName(id: string | null): string {
  if (!id) return ''
  return planOptions.value.items.find((x) => x.id === id)?.title || '未命名地点'
}

function emptyForm() {
  return {
    mode: 'train', from_name: '', to_name: '', from_lng: '', from_lat: '',
    to_lng: '', to_lat: '', depart_at: '', arrive_at: '', carrier: '', seat: '', price: '',
    day_id: '', plan_item_id: '',
  }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function toLocalInput(v: string | null): string { return v ? v.slice(0, 16) : '' }

async function loadPlanOptions() {
  try {
    planOptions.value = await api.get<PlanOptions>(`/trips/${encodeURIComponent(tripId.value)}/plan/options`)
  } catch {
    planOptions.value = { days: [], items: [] }
  }
}

async function load() {
  loading.value = true
  error.value = ''
  const url = dayFilter.value ? `${base.value}?day_id=${encodeURIComponent(dayFilter.value)}` : base.value
  try { items.value = await api.get<Transport[]>(url) } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

function onFilterChange() { void load() }

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogOpen.value = true
}
function openEdit(t: Transport) {
  editingId.value = t.id
  Object.assign(form, {
    mode: t.mode || 'other', from_name: t.from_name || '', to_name: t.to_name || '',
    from_lng: t.from_lng === null ? '' : String(t.from_lng), from_lat: t.from_lat === null ? '' : String(t.from_lat),
    to_lng: t.to_lng === null ? '' : String(t.to_lng), to_lat: t.to_lat === null ? '' : String(t.to_lat),
    depart_at: toLocalInput(t.depart_at), arrive_at: toLocalInput(t.arrive_at),
    carrier: t.carrier || '', seat: t.seat || '', price: t.price === null ? '' : String(t.price),
    day_id: t.day_id || '', plan_item_id: t.plan_item_id || '',
  })
  dialogOpen.value = true
}

function num(v: string): number | null {
  if (v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
function body() {
  return {
    mode: form.mode, from_name: form.from_name || null, to_name: form.to_name || null,
    // 用户输入的经纬度按 WGS84 坐标系标记（与后端约定一致）
    from_lng: num(form.from_lng), from_lat: num(form.from_lat),
    to_lng: num(form.to_lng), to_lat: num(form.to_lat), coord_system: 'WGS84',
    depart_at: form.depart_at || null, arrive_at: form.arrive_at || null,
    carrier: form.carrier || null, seat: form.seat || null, price: num(form.price),
    day_id: form.day_id || null, plan_item_id: form.plan_item_id || null,
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    if (editingId.value) await api.put(`${base.value}/${editingId.value}`, body())
    else await api.post(base.value, body())
    dialogOpen.value = false
    await load()
  } catch (e) { error.value = messageOf(e) } finally { saving.value = false }
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  error.value = ''
  try { await api.del(`${base.value}/${deleteTarget.value.id}`); await load() } catch (e) { error.value = messageOf(e) } finally { deleting.value = false; deleteTarget.value = null }
}

onMounted(() => { void Promise.all([load(), loadPlanOptions()]) })
</script>

<template>
  <div class="mx-auto max-w-[1100px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Route class="h-5 w-5 text-primary" /> 交通</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">城际与市内交通段落，起终点坐标按全球通用坐标系入库</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新增段落</Button>
    </div>

    <!-- 按行程日筛选 -->
    <div class="flex items-center gap-2">
      <CalendarDays class="h-3.5 w-3.5 text-muted-foreground" />
      <label class="text-xs text-muted-foreground">按行程日查看</label>
      <div class="w-56"><Select v-model="dayFilter" :options="dayFilterOptions" @update:model-value="onFilterChange" /></div>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载中…</div>

    <template v-else>
      <EmptyState v-if="!items.length" title="还没有交通段落" description="记录车次、航班与起终点，方便串联行程。" :icon="Route">
        <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新增第一段</Button>
      </EmptyState>
      <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div v-for="t in items" :key="t.id" class="rounded-lg border border-border bg-card p-3">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="flex items-center gap-1.5 text-sm font-medium text-foreground">
                <Badge variant="outline">{{ modeLabel(t.mode) }}</Badge>
                <span class="truncate">{{ t.from_name || '起点' }}</span>
                <span class="text-muted-foreground">→</span>
                <span class="truncate">{{ t.to_name || '终点' }}</span>
              </div>
              <p class="mt-1.5 text-[11px] text-muted-foreground">
                {{ formatDate(t.depart_at) }}<span v-if="t.arrive_at"> → {{ formatDate(t.arrive_at) }}</span>
                <span v-if="t.carrier"> · {{ t.carrier }}</span><span v-if="t.seat"> · {{ t.seat }}</span>
              </p>
              <p v-if="dayName(t.day_id) || itemName(t.plan_item_id)" class="mt-1 text-[11px] text-primary">
                <span v-if="dayName(t.day_id)">{{ dayName(t.day_id) }}</span>
                <span v-if="itemName(t.plan_item_id)"> · {{ itemName(t.plan_item_id) }}</span>
              </p>
              <p v-if="t.from_lng !== null || t.to_lng !== null" class="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground">
                <MapPin class="h-2.5 w-2.5" /> 已记录坐标 · {{ t.coord_system }} 坐标系
              </p>
            </div>
            <span class="shrink-0 text-xs text-foreground">{{ formatMoney(t.price) }}</span>
          </div>
          <div class="mt-3 flex justify-end gap-1.5 border-t border-border pt-2">
            <Button variant="outline" size="sm" @click="openEdit(t)"><Pencil class="h-3.5 w-3.5" /> 编辑</Button>
            <Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" @click="deleteTarget = t"><Trash2 class="h-3.5 w-3.5" /> 删除</Button>
          </div>
        </div>
      </div>
    </template>

    <Dialog v-model="dialogOpen" :title="editingId ? '编辑交通段落' : '新增交通段落'" width="max-w-lg">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="space-y-1"><label class="text-xs font-medium">方式</label><Select v-model="form.mode" :options="modeOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">承运方</label><Input v-model="form.carrier" placeholder="航司 / 铁路局" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">起点名称</label><Input v-model="form.from_name" placeholder="例如：杭州东站" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">终点名称</label><Input v-model="form.to_name" placeholder="例如：黄山北站" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">出发时间</label><Input v-model="form.depart_at" type="datetime-local" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">到达时间</label><Input v-model="form.arrive_at" type="datetime-local" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">座位 / 车次</label><Input v-model="form.seat" placeholder="可选" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">价格</label><Input v-model="form.price" type="number" step="0.01" placeholder="0.00" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">起点经度</label><Input v-model="form.from_lng" type="number" step="any" placeholder="全球通用坐标系经度" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">起点纬度</label><Input v-model="form.from_lat" type="number" step="any" placeholder="全球通用坐标系纬度" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">终点经度</label><Input v-model="form.to_lng" type="number" step="any" placeholder="全球通用坐标系经度" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">终点纬度</label><Input v-model="form.to_lat" type="number" step="any" placeholder="全球通用坐标系纬度" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">所属行程日</label><Select v-model="form.day_id" :options="daySelectOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">关联地点</label><Select v-model="form.plan_item_id" :options="itemSelectOptions" /></div>
      </div>
      <p class="mt-2 text-[10px] text-muted-foreground">坐标以全球通用坐标系（WGS84）保存；渲染地图时会按底图坐标系自动换算。</p>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="saving" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="saving" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /> 保存</Button>
      </template>
    </Dialog>

    <ConfirmDialog
      :model-value="!!deleteTarget"
      title="删除交通段落"
      message="删除后该段落将不再显示，确定继续吗？"
      danger
      :busy="deleting"
      @update:model-value="(v) => { if (!v) deleteTarget = null }"
      @confirm="confirmDelete"
    />
  </div>
</template>
