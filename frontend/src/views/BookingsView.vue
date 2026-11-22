<script setup lang="ts">
/** 预订页：/trips/{id}/bookings 标准 CRUD（写端点需 booking:write 权限）。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plane, Plus, Trash2, Pencil, Loader2 } from 'lucide-vue-next'
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
}

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

function emptyForm() {
  return { type: 'flight', vendor: '', booking_no: '', holder: '', start_at: '', end_at: '', amount: '', currency: 'CNY', status: 'pending', note: '' }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}

async function load() {
  loading.value = true
  error.value = ''
  try { items.value = await api.get<Booking[]>(base.value) } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

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
  })
  dialogOpen.value = true
}
function toLocalInput(v: string | null): string {
  if (!v) return ''
  return v.slice(0, 16) // datetime-local 只取 YYYY-MM-DDTHH:mm
}

function body() {
  return {
    type: form.type, vendor: form.vendor || null, booking_no: form.booking_no || null,
    holder: form.holder || null, start_at: form.start_at || null, end_at: form.end_at || null,
    amount: form.amount === '' ? null : Number(form.amount), currency: form.currency || 'CNY',
    status: form.status || 'pending', note: form.note || null,
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

onMounted(load)
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

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载中…</div>

    <template v-else>
      <EmptyState v-if="!items.length" title="还没有预订记录" description="把机票、酒店、门票的确认信息记在这里。" :icon="Plane">
        <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 新增第一条</Button>
      </EmptyState>
      <div v-else class="overflow-x-auto rounded-lg border border-border bg-card">
        <table class="w-full text-left text-xs">
          <thead class="border-b border-border text-muted-foreground">
            <tr>
              <th class="px-3 py-2 font-medium">类型 / 供应商</th>
              <th class="px-3 py-2 font-medium">预订号</th>
              <th class="px-3 py-2 font-medium">时间</th>
              <th class="px-3 py-2 font-medium">金额</th>
              <th class="px-3 py-2 font-medium">状态</th>
              <th class="px-3 py-2" />
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="b in items" :key="b.id" class="hover:bg-muted/40">
              <td class="px-3 py-2">
                <span class="block font-medium text-foreground">{{ b.vendor || '未填写供应商' }}</span>
                <span class="text-[10px] text-muted-foreground">{{ typeLabel(b.type) }}<span v-if="b.holder"> · {{ b.holder }}</span></span>
              </td>
              <td class="px-3 py-2 font-mono text-[11px] text-foreground">{{ b.booking_no || '—' }}</td>
              <td class="px-3 py-2 text-muted-foreground">{{ formatDate(b.start_at) }}<span v-if="b.end_at"> → {{ formatDate(b.end_at) }}</span></td>
              <td class="px-3 py-2 text-foreground">{{ formatMoney(b.amount, b.currency) }}</td>
              <td class="px-3 py-2 text-muted-foreground">{{ statusLabel(b.status) }}</td>
              <td class="px-3 py-2 text-right">
                <Button variant="ghost" size="sm" class="h-7 w-7 p-0" title="编辑" @click="openEdit(b)"><Pencil class="h-3.5 w-3.5" /></Button>
                <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-muted-foreground hover:text-destructive" title="删除" @click="deleteTarget = b"><Trash2 class="h-3.5 w-3.5" /></Button>
              </td>
            </tr>
          </tbody>
        </table>
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
        <div class="space-y-1"><label class="text-xs font-medium">币种</label><Input v-model="form.currency" placeholder="CNY" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">开始时间</label><Input v-model="form.start_at" type="datetime-local" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">结束时间</label><Input v-model="form.end_at" type="datetime-local" /></div>
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
