<script setup lang="ts">
/** 费用页：/trips/{id}/expenses CRUD + /expenses/summary 汇总（按分类 / 币种）。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Wallet, Plus, Trash2, Pencil, Loader2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { formatDate, formatMoney } from '@/lib/utils'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

interface Expense {
  id: string
  category: string
  amount: number
  currency: string
  exchange_rate: number | null
  paid_by: string | null
  occurred_at: string | null
  note: string | null
}
interface Summary {
  total: number
  byCategory: Record<string, number>
  byCurrency: Record<string, number>
  count: number
}

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/expenses`)
const items = ref<Expense[]>([])
const summary = ref<Summary | null>(null)
const loading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const deleteTarget = ref<Expense | null>(null)
const deleting = ref(false)

const categoryOptions = [
  { value: 'food', label: '餐饮' }, { value: 'lodging', label: '住宿' },
  { value: 'transport', label: '交通' }, { value: 'ticket', label: '门票' },
  { value: 'shopping', label: '购物' }, { value: 'other', label: '其他' },
]
const categoryLabel = (v: string) => categoryOptions.find((o) => o.value === v)?.label ?? v

function emptyForm() {
  return { category: 'food', amount: '', currency: 'CNY', exchange_rate: '', paid_by: '', occurred_at: '', note: '' }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function toLocalInput(v: string | null): string { return v ? v.slice(0, 16) : '' }

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [list, sum] = await Promise.all([
      api.get<Expense[]>(base.value),
      api.get<Summary>(`${base.value}/summary`).catch(() => null),
    ])
    items.value = list ?? []
    summary.value = sum
  } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogOpen.value = true
}
function openEdit(x: Expense) {
  editingId.value = x.id
  Object.assign(form, {
    category: x.category || 'other', amount: String(x.amount ?? ''), currency: x.currency || 'CNY',
    exchange_rate: x.exchange_rate === null ? '' : String(x.exchange_rate),
    paid_by: x.paid_by || '', occurred_at: toLocalInput(x.occurred_at), note: x.note || '',
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
    category: form.category, amount: form.amount === '' ? 0 : Number(form.amount),
    currency: form.currency || 'CNY', exchange_rate: num(form.exchange_rate),
    paid_by: form.paid_by || null, occurred_at: form.occurred_at || null, note: form.note || null,
  }
}

async function save() {
  if (saving.value) return
  if (form.amount === '' || !Number.isFinite(Number(form.amount))) { error.value = '请填写有效金额'; return }
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

const topCategories = computed(() => {
  const s = summary.value
  if (!s) return []
  return Object.entries(s.byCategory).sort((a, b) => b[1] - a[1]).slice(0, 6)
})

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-[1100px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Wallet class="h-5 w-5 text-primary" /> 费用</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">按分类与币种记录开销，有汇率时折算本位币计入合计</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 记一笔</Button>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>

    <!-- 汇总 -->
    <div v-if="summary" class="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card>
        <p class="text-[11px] text-muted-foreground">折算合计</p>
        <p class="mt-1 text-2xl font-semibold text-foreground">{{ formatMoney(summary.total, 'CNY') }}</p>
        <p class="mt-1 text-[11px] text-muted-foreground">共 {{ summary.count }} 笔</p>
      </Card>
      <Card>
        <p class="mb-2 text-[11px] text-muted-foreground">按分类</p>
        <div class="space-y-1">
          <div v-for="[k, v] in topCategories" :key="k" class="flex items-center justify-between text-xs">
            <span class="text-muted-foreground">{{ categoryLabel(k) }}</span>
            <span class="font-medium text-foreground">{{ formatMoney(v, 'CNY') }}</span>
          </div>
          <p v-if="!topCategories.length" class="text-xs text-muted-foreground">暂无数据</p>
        </div>
      </Card>
      <Card>
        <p class="mb-2 text-[11px] text-muted-foreground">按币种（未折算）</p>
        <div class="space-y-1">
          <div v-for="(v, k) in summary.byCurrency" :key="k" class="flex items-center justify-between text-xs">
            <span class="text-muted-foreground">{{ k }}</span>
            <span class="font-medium text-foreground">{{ formatMoney(v, k) }}</span>
          </div>
          <p v-if="!Object.keys(summary.byCurrency).length" class="text-xs text-muted-foreground">暂无数据</p>
        </div>
      </Card>
    </div>

    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载中…</div>

    <template v-else>
      <EmptyState v-if="!items.length" title="还没有费用记录" description="把每一笔餐饮、住宿、门票开销记下来。" :icon="Wallet">
        <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 记第一笔</Button>
      </EmptyState>
      <div v-else class="overflow-x-auto rounded-lg border border-border bg-card">
        <table class="w-full text-left text-xs">
          <thead class="border-b border-border text-muted-foreground">
            <tr>
              <th class="px-3 py-2 font-medium">分类 / 备注</th>
              <th class="px-3 py-2 font-medium">金额</th>
              <th class="px-3 py-2 font-medium">汇率</th>
              <th class="px-3 py-2 font-medium">支付人</th>
              <th class="px-3 py-2 font-medium">时间</th>
              <th class="px-3 py-2" />
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="x in items" :key="x.id" class="hover:bg-muted/40">
              <td class="px-3 py-2">
                <Badge variant="outline">{{ categoryLabel(x.category) }}</Badge>
                <span class="ml-2 text-muted-foreground">{{ x.note || '—' }}</span>
              </td>
              <td class="px-3 py-2 font-medium text-foreground">{{ formatMoney(x.amount, x.currency) }}</td>
              <td class="px-3 py-2 text-muted-foreground">{{ x.exchange_rate ?? '—' }}</td>
              <td class="px-3 py-2 text-muted-foreground">{{ x.paid_by || '—' }}</td>
              <td class="px-3 py-2 text-muted-foreground">{{ formatDate(x.occurred_at) }}</td>
              <td class="px-3 py-2 text-right">
                <Button variant="ghost" size="sm" class="h-7 w-7 p-0" title="编辑" @click="openEdit(x)"><Pencil class="h-3.5 w-3.5" /></Button>
                <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-muted-foreground hover:text-destructive" title="删除" @click="deleteTarget = x"><Trash2 class="h-3.5 w-3.5" /></Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <Dialog v-model="dialogOpen" :title="editingId ? '编辑费用' : '记一笔费用'" width="max-w-lg">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="space-y-1"><label class="text-xs font-medium">分类</label><Select v-model="form.category" :options="categoryOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">金额</label><Input v-model="form.amount" type="number" step="0.01" placeholder="0.00" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">币种</label><Input v-model="form.currency" placeholder="CNY" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">折算汇率</label><Input v-model="form.exchange_rate" type="number" step="any" placeholder="留空按 1.0" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">支付人</label><Input v-model="form.paid_by" placeholder="可选" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">发生时间</label><Input v-model="form.occurred_at" type="datetime-local" /></div>
        <div class="space-y-1 sm:col-span-2"><label class="text-xs font-medium">备注</label><Input v-model="form.note" placeholder="可选" /></div>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="saving" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="saving" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /> 保存</Button>
      </template>
    </Dialog>

    <ConfirmDialog
      :model-value="!!deleteTarget"
      title="删除费用记录"
      message="删除后该金额将不再计入汇总，确定继续吗？"
      danger
      :busy="deleting"
      @update:model-value="(v) => { if (!v) deleteTarget = null }"
      @confirm="confirmDelete"
    />
  </div>
</template>
