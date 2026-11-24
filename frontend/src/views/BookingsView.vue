<script setup lang="ts">
/** 预订页：/trips/{id}/bookings 标准 CRUD（写端点需 booking:write 权限）。
 *  支持关联「所属行程日 / 关联地点」（GET /plan/options），列表可按 day_id 筛选。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plane, Plus, Trash2, Pencil, Loader2, CalendarDays } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { formatDate, formatMoney } from '@/lib/utils'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

interface Booking {
  id: string
  type: string
  vendor: string | null
  booking_no: string | null
  holder: string | null
  start_at: string | null
  end_at: string | null
  amount: number | null
  currency: string
  status: string
  note: string | null
  day_id: string | null
  plan_item_id: string | null
}

/** 行程日与计划项下拉数据，来自 GET /trips/{id}/plan/options。 */
interface PlanDay { id: string; day_index: number; date: string | null; title: string | null }
interface PlanItem { id: string; title: string | null; type: string | null; day_id: string | null }
interface PlanOptions { days: PlanDay[]; items: PlanItem[] }

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/bookings`)
const items = ref<Booking[]>([])
const loading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const deleteTarget = ref<Booking | null>(null)
const deleting = ref(false)

const planOptions = ref<PlanOptions>({ days: [], items: [] })
const dayFilter = ref('')

const typeOptions = [
  { value: 'flight', label: '机票' }, { value: 'hotel', label: '酒店' },
  { value: 'train', label: '火车' }, { value: 'ticket', label: '门票' },
  { value: 'other', label: '其他' },
]
const statusOptions = [
  { value: 'pending', label: '待确认' }, { value: 'confirmed', label: '已确认' },
  { value: 'cancelled', label: '已取消' },
]
const typeLabel = (v: string) => typeOptions.find((o) => o.value === v)?.label ?? v
const statusLabel = (v: string) => statusOptions.find((o) => o.value === v)?.label ?? v

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
    type: 'flight', vendor: '', booking_no: '', holder: '', start_at: '', end_at: '',
    amount: '', currency: 'CNY', status: 'pending', note: '', day_id: '', plan_item_id: '',
  }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}

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
  try { items.value = await api.get<Booking[]>(url) } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

function onFilterChange() { void load() }

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogOpen.value = true
}
function openEdit(b: Booking) {
  editingId.value = b.id
  Object.assign(form, {
    type: b.type || 'other', vendor: b.vendor || '', booking_no: b.booking_no || '',
    holder: b.holder || '', start_at: toLocalInput(b.start_at), end_at: toLocalInput(b.end_at),
    amount: b.amount === null ? '' : String(b.amount), currency: b.currency || 'CNY',
    status: b.status || 'pending', note: b.note || '',
    day_id: b.day_id || '', plan_item_id: b.plan_item_id || '',
  })
  dialogOpen.value = true
}
function toLocalInput(v: string | null): string {
  if (!v) return ''
  return v.slice(0, 16) // 时间输入只取「年-月-日T时:分」
}

function body() {
  return {
    type: form.type, vendor: form.vendor || null, booking_no: form.booking_no || null,
    holder: form.holder || null, start_at: form.start_at || null, end_at: form.end_at || null,
    amount: form.amount === '' ? null : Number(form.amount), currency: form.currency || 'CNY',
    status: form.status || 'pending', note: form.note || null,
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
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Plane class="h-5 w-5 text-primary" /> 预订</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">机票、酒店、火车与门票记录</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新增预订</Button>
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
      <EmptyState v-if="!items.length" title="还没有预订记录" description="把机票、酒店、门票的确认信息记在这里。" :icon="Plane">
        <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新增第一条</Button>
      </EmptyState>
      <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <article v-for="b in items" :key="b.id" class="group overflow-hidden rounded-xl border border-border bg-card shadow-sm transition-shadow hover:shadow-md">
          <div class="flex items-center justify-between border-b border-border bg-muted/35 px-4 py-3">
            <div class="flex min-w-0 items-center gap-2">
              <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Plane class="size-4" /></span>
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold text-foreground">{{ b.vendor || '未填写供应商' }}</p>
                <p class="text-[10px] text-muted-foreground">{{ typeLabel(b.type) }}<span v-if="b.holder"> · {{ b.holder }}</span></p>
              </div>
            </div>
            <span class="rounded-full bg-secondary px-2 py-1 text-[10px] font-medium text-secondary-foreground">{{ statusLabel(b.status) }}</span>
          </div>
          <div class="space-y-3 p-4">
            <div class="grid grid-cols-2 gap-2 rounded-lg bg-muted/35 p-3">
              <div><p class="text-[10px] text-muted-foreground">开始时间</p><p class="mt-1 text-xs font-medium text-foreground">{{ formatDate(b.start_at) || '待安排' }}</p></div>
              <div><p class="text-[10px] text-muted-foreground">结束时间</p><p class="mt-1 text-xs font-medium text-foreground">{{ formatDate(b.end_at) || '—' }}</p></div>
            </div>
            <div class="flex items-end justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-muted-foreground">预订编号</p>
                <p class="truncate font-mono text-xs font-medium text-foreground">{{ b.booking_no || '未填写' }}</p>
              </div>
              <div class="shrink-0 text-right">
                <p class="text-[10px] text-muted-foreground">金额</p>
                <p class="mt-0.5 text-sm font-semibold text-foreground">{{ formatMoney(b.amount, b.currency) }}</p>
              </div>
            </div>
            <div class="space-y-1 border-t border-border pt-2 text-[11px] text-muted-foreground">
              <p v-if="dayName(b.day_id)" class="flex items-center gap-1.5"><CalendarDays class="size-3 shrink-0" />{{ dayName(b.day_id) }}</p>
              <p v-if="itemName(b.plan_item_id)" class="truncate">关联地点：{{ itemName(b.plan_item_id) }}</p>
              <p v-if="b.note" class="line-clamp-2">{{ b.note }}</p>
              <p v-if="!dayName(b.day_id) && !itemName(b.plan_item_id) && !b.note" class="text-muted-foreground/70">暂无补充信息</p>
            </div>
          </div>
          <div class="flex justify-end gap-1.5 border-t border-border px-4 py-3">
            <Button variant="outline" size="sm" @click="openEdit(b)"><Pencil class="h-3.5 w-3.5" /> 编辑</Button>
            <Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" @click="deleteTarget = b"><Trash2 class="h-3.5 w-3.5" /> 删除</Button>
          </div>
        </article>
      </div>
    </template>

    <Dialog v-model="dialogOpen" :title="editingId ? '编辑预订' : '新增预订'" width="max-w-lg">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="space-y-1"><label class="text-xs font-medium">类型</label><Select v-model="form.type" :options="typeOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">状态</label><Select v-model="form.status" :options="statusOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">供应商</label><Input v-model="form.vendor" placeholder="航司 / 酒店名" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">预订号</label><Input v-model="form.booking_no" placeholder="确认编号" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">持有人</label><Input v-model="form.holder" placeholder="出行人" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">金额</label><Input v-model="form.amount" type="number" step="0.01" placeholder="0.00" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">币种</label><Input v-model="form.currency" placeholder="例如：CNY" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">开始时间</label><Input v-model="form.start_at" type="datetime-local" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">结束时间</label><Input v-model="form.end_at" type="datetime-local" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">所属行程日</label><Select v-model="form.day_id" :options="daySelectOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">关联地点</label><Select v-model="form.plan_item_id" :options="itemSelectOptions" /></div>
        <div class="space-y-1 sm:col-span-2"><label class="text-xs font-medium">备注</label><Input v-model="form.note" placeholder="可选" /></div>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="saving" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="saving" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /> 保存</Button>
      </template>
    </Dialog>

    <ConfirmDialog
      :model-value="!!deleteTarget"
      title="删除预订"
      message="删除后该记录将不再显示，确定继续吗？"
      danger
      :busy="deleting"
      @update:model-value="(v) => { if (!v) deleteTarget = null }"
      @confirm="confirmDelete"
    />
  </div>
</template>
