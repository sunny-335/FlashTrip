<script setup lang="ts">
/** 费用页：CRUD + 汇总 + 多人智能分账。
 *  - 关联「所属行程日 / 关联地点」，列表可按 day_id 筛选；
 *  - 汇总卡片展示分账方式 / 参与人 / 按成员应摊；
 *  - 分账面板展示每位成员垫付、应摊、余额与建议转账；
 *  - 单笔费用可设置分账方式、儿童免账、家庭分组，保存后展示明细份额。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Wallet, Plus, Trash2, Pencil, Loader2, CalendarDays, Users, ArrowRightLeft, RefreshCw, Target } from 'lucide-vue-next'
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
  day_id: string | null
  plan_item_id: string | null
  split_mode: string | null
}

/** 汇总：原有四字段 + 分账维度 splitMode / participants / byParticipant。 */
interface SplitParticipant {
  id: string; name: string; is_child: boolean; family: string
  paid: number; owed: number; balance: number
}
interface Summary {
  total: number
  byCategory: Record<string, number>
  byCurrency: Record<string, number>
  count: number
  splitMode?: string
  participants?: SplitParticipant[]
  byParticipant?: Record<string, number>
}
/** 分账汇总：垫付、应摊、余额与建议转账。 */
interface Transfer { from: string; to: string; amount: number }
interface SplitSummary {
  total: number
  payerTotal: number
  participants: SplitParticipant[]
  suggestedTransfers: Transfer[]
  travelerCount: number
  childrenCount: number
  childFree: boolean
}
interface Share { participant_id: string; share: number; amount: number }

/** 行程日与计划项下拉数据，来自 GET /trips/{id}/plan/options。 */
interface PlanDay { id: string; day_index: number; date: string | null; title: string | null }
interface PlanItem { id: string; title: string | null; type: string | null; day_id: string | null }
interface PlanOptions { days: PlanDay[]; items: PlanItem[] }

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/expenses`)
const items = ref<Expense[]>([])
interface BudgetComparison { total_budget: number | null; total_spent: number; total_remaining: number | null; by_category: { category: string; budget: number | null; spent: number; remaining: number | null; over_budget: boolean }[] }
const budget = ref<BudgetComparison | null>(null)
const budgetInput = ref('')
const budgetSaving = ref(false)
const summary = ref<Summary | null>(null)
const splitSummary = ref<SplitSummary | null>(null)
const loading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const deleteTarget = ref<Expense | null>(null)
const deleting = ref(false)

const planOptions = ref<PlanOptions>({ days: [], items: [] })
const dayFilter = ref('')

const categoryOptions = [
  { value: 'food', label: '餐饮' }, { value: 'lodging', label: '住宿' },
  { value: 'transport', label: '交通' }, { value: 'ticket', label: '门票' },
  { value: 'shopping', label: '购物' }, { value: 'other', label: '其他' },
]
const categoryLabel = (v: string) => categoryOptions.find((o) => o.value === v)?.label ?? v

/** 五种分账方式，中文标签与后端 split_mode 一一对应。 */
const splitModeOptions = [
  { value: 'equal', label: '按人数均摊' },
  { value: 'child_free', label: '儿童免账（仅成人分摊）' },
  { value: 'family', label: '按家庭分组分摊' },
  { value: 'custom', label: '自定义份额' },
  { value: 'payer_only', label: '仅记垫付人' },
]
const splitModeLabel = (v: string | null | undefined) =>
  splitModeOptions.find((o) => o.value === v)?.label ?? (v || '按人数均摊')

/** 表单下拉：首项为「不关联」。 */
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
    category: 'food', amount: '', currency: 'CNY', exchange_rate: '', paid_by: '',
    occurred_at: '', note: '', day_id: '', plan_item_id: '', split_mode: 'equal',
  }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function toLocalInput(v: string | null): string { return v ? v.slice(0, 16) : '' }
/** 金额统一用「元」展示，避免把币种英文写进中文界面。 */
function money(v: number | null | undefined): string {
  return `${Number(v ?? 0).toFixed(2)} 元`
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
  try {
    const [list, sum, split, comparison] = await Promise.all([
      api.get<Expense[]>(url),
      api.get<Summary>(`${base.value}/summary`).catch(() => null),
      api.get<SplitSummary>(`${base.value}/split-summary`).catch(() => null),
      api.get<BudgetComparison>(`/trips/${encodeURIComponent(tripId.value)}/budget/comparison`).catch(() => null),
    ])
    items.value = list ?? []
    summary.value = sum
    splitSummary.value = split
    budget.value = comparison
    budgetInput.value = comparison?.total_budget == null ? '' : String(comparison.total_budget)
  } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

function onFilterChange() { void load() }

async function saveBudget() {
  budgetSaving.value = true
  try {
    await api.put(`/trips/${encodeURIComponent(tripId.value)}/budget`, { total_budget: budgetInput.value === '' ? null : Number(budgetInput.value) })
    budget.value = await api.get<BudgetComparison>(`/trips/${encodeURIComponent(tripId.value)}/budget/comparison`)
  } catch (e) { error.value = messageOf(e) } finally { budgetSaving.value = false }
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
    day_id: x.day_id || '', plan_item_id: x.plan_item_id || '',
    split_mode: x.split_mode || 'equal',
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
    day_id: form.day_id || null, plan_item_id: form.plan_item_id || null,
    split_mode: form.split_mode,
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

// ---------------------------------------------------------------- 单笔费用分账
interface SplitRow { id: string; name: string; is_child: boolean; family: string; share: number }
const splitTarget = ref<Expense | null>(null)
const splitOpen = ref(false)
const splitSaving = ref(false)
const splitError = ref('')
const splitForm = reactive({ split_mode: 'equal', child_free: false, note: '' })
const splitRows = ref<SplitRow[]>([])
const splitShares = ref<Share[]>([])

/** 参与者姓名：优先用分账汇总里的名字，未指定垫付人用中文兜底。 */
function participantName(id: string): string {
  const p = splitSummary.value?.participants.find((x) => x.id === id)
  if (p) return p.name
  return id === '__unassigned__' ? '未指定垫付人' : id
}

function openSplit(x: Expense) {
  splitTarget.value = x
  splitForm.split_mode = x.split_mode || 'equal'
  splitForm.child_free = x.split_mode === 'child_free'
  splitForm.note = ''
  splitShares.value = []
  splitError.value = ''
  // 以行程级参与者为可编辑基础，家庭分组与份额由用户逐项调整
  splitRows.value = (splitSummary.value?.participants ?? []).map((p) => ({
    id: p.id, name: p.name, is_child: p.is_child, family: p.family || '', share: 1,
  }))
  splitOpen.value = true
}

async function saveSplit() {
  const target = splitTarget.value
  if (!target || splitSaving.value) return
  splitSaving.value = true
  splitError.value = ''
  try {
    const payload: Record<string, unknown> = {
      split_mode: splitForm.split_mode,
      child_free: splitForm.child_free,
      note: splitForm.note || '',
      participants: splitRows.value.map((r) => ({
        id: r.id, name: r.name, is_child: r.is_child, family: r.family,
      })),
    }
    // 自定义份额把每人填写的相对份额提交给后端作为分摊权重
    if (splitForm.split_mode === 'custom') {
      payload.shares = splitRows.value.map((r) => ({
        participant_id: r.id, share: Number(r.share) || 0,
      }))
    }
    const res = await api.post<{ expense: Expense; shares: Share[] }>(
      `${base.value}/${target.id}/split`, payload,
    )
    splitShares.value = res.shares ?? []
    await load()
  } catch (e) {
    splitError.value = messageOf(e)
  } finally {
    splitSaving.value = false
  }
}

onMounted(() => { void Promise.all([load(), loadPlanOptions()]) })
</script>

<template>
  <div class="mx-auto max-w-[1100px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Wallet class="h-5 w-5 text-primary" /> 费用</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">按分类与币种记录开销，有汇率时折算本位币计入合计</p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="load"><RefreshCw class="h-3.5 w-3.5" /> 刷新</Button>
        <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 记一笔</Button>
      </div>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>

    <!-- 汇总卡片：合计、按分类、按币种、分账概览 -->
    <div v-if="summary" class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Card>
        <p class="text-[11px] text-muted-foreground">折算合计</p>
        <p class="mt-1 text-2xl font-semibold text-foreground">{{ money(summary.total) }}</p>
        <p class="mt-1 text-[11px] text-muted-foreground">共 {{ summary.count }} 笔</p>
      </Card>
      <Card>
        <p class="mb-2 text-[11px] text-muted-foreground">按分类</p>
        <div class="space-y-1">
          <div v-for="[k, v] in topCategories" :key="k" class="flex items-center justify-between text-xs">
            <span class="text-muted-foreground">{{ categoryLabel(k) }}</span>
            <span class="font-medium text-foreground">{{ money(v) }}</span>
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
      <Card>
        <p class="mb-2 flex items-center gap-1 text-[11px] text-muted-foreground"><Users class="h-3 w-3" /> 分账概览</p>
        <p class="text-xs text-foreground">主要方式：{{ splitModeLabel(summary.splitMode) }}</p>
        <p class="mt-1 text-xs text-muted-foreground">参与 {{ summary.participants?.length ?? 0 }} 人</p>
        <div v-if="summary.byParticipant && Object.keys(summary.byParticipant).length" class="mt-1.5 space-y-0.5">
          <div v-for="(v, k) in summary.byParticipant" :key="k" class="flex items-center justify-between text-[11px]">
            <span class="truncate text-muted-foreground">{{ participantName(k) }} 应摊</span>
            <span class="font-medium text-foreground">{{ money(v) }}</span>
          </div>
        </div>
      </Card>
    </div>

    <Card class="space-y-3">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div><h2 class="flex items-center gap-2 text-sm font-semibold"><Target class="h-4 w-4 text-primary" /> 行程预算</h2><p class="mt-1 text-xs text-muted-foreground">预算对比数据由预算 API 提供</p></div>
        <div class="flex items-center gap-2"><Input v-model="budgetInput" type="number" min="0" step="0.01" class="w-36" placeholder="总预算（元）" /><Button size="sm" :disabled="budgetSaving" @click="saveBudget">保存预算</Button></div>
      </div>
      <div v-if="budget" class="space-y-2 text-xs">
        <p>已用 {{ money(budget.total_spent) }}<span v-if="budget.total_budget != null"> / {{ money(budget.total_budget) }} · 剩余 {{ money(budget.total_remaining) }}</span><span v-else> · 尚未设置总预算</span></p>
        <div v-for="row in budget.by_category" :key="row.category" class="flex justify-between rounded-md bg-muted/40 px-2.5 py-1.5"><span>{{ categoryLabel(row.category) }}</span><span :class="row.over_budget ? 'text-destructive' : ''">{{ money(row.spent) }} / {{ row.budget == null ? '未设预算' : money(row.budget) }}<span v-if="row.over_budget"> · 已超支</span></span></div>
      </div>
    </Card>

    <!-- 多人智能分账面板 -->
    <Card v-if="splitSummary" class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="flex items-center gap-2 text-sm font-semibold"><ArrowRightLeft class="h-4 w-4 text-primary" /> 多人智能分账</h2>
        <div class="flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
          <span>合计 {{ money(splitSummary.total) }}</span>
          <span>· 已垫付 {{ money(splitSummary.payerTotal) }}</span>
          <span>· 共 {{ splitSummary.travelerCount }} 人</span>
          <span v-if="splitSummary.childrenCount">· 儿童 {{ splitSummary.childrenCount }} 人</span>
          <span v-if="splitSummary.childFree">· 已启用儿童免账</span>
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border border-border">
        <table class="w-full text-left text-xs">
          <thead class="border-b border-border bg-muted/40 text-muted-foreground">
            <tr>
              <th class="px-3 py-2 font-medium">成员</th>
              <th class="px-3 py-2 font-medium">分组</th>
              <th class="px-3 py-2 font-medium">垫付</th>
              <th class="px-3 py-2 font-medium">应摊</th>
              <th class="px-3 py-2 font-medium">余额</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="p in splitSummary.participants" :key="p.id">
              <td class="px-3 py-2">
                <span class="font-medium text-foreground">{{ p.name }}</span>
                <Badge v-if="p.is_child" variant="outline" class="ml-1.5">儿童</Badge>
              </td>
              <td class="px-3 py-2 text-muted-foreground">{{ p.family ? `家庭 ${p.family}` : '—' }}</td>
              <td class="px-3 py-2 text-foreground">{{ money(p.paid) }}</td>
              <td class="px-3 py-2 text-foreground">{{ money(p.owed) }}</td>
              <td class="px-3 py-2">
                <span :class="p.balance > 0 ? 'text-primary' : p.balance < 0 ? 'text-destructive' : 'text-muted-foreground'">
                  {{ money(p.balance) }}
                  <span class="text-[10px]">{{ p.balance > 0 ? '应收回' : p.balance < 0 ? '应付出' : '已结清' }}</span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div>
        <p class="mb-1.5 text-xs font-medium">建议转账</p>
        <div v-if="splitSummary.suggestedTransfers.length" class="space-y-1">
          <p v-for="(t, i) in splitSummary.suggestedTransfers" :key="i" class="rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground">
            {{ participantName(t.from) }} 向 {{ participantName(t.to) }} 转账 <span class="font-medium text-primary">{{ money(t.amount) }}</span>
          </p>
        </div>
        <p v-else class="text-xs text-muted-foreground">当前账目已平衡，无需转账。</p>
      </div>
    </Card>

    <!-- 按行程日筛选 -->
    <div class="flex items-center gap-2">
      <CalendarDays class="h-3.5 w-3.5 text-muted-foreground" />
      <label class="text-xs text-muted-foreground">按行程日查看</label>
      <div class="w-56"><Select v-model="dayFilter" :options="dayFilterOptions" @update:model-value="onFilterChange" /></div>
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
              <th class="px-3 py-2 font-medium">支付人</th>
              <th class="px-3 py-2 font-medium">时间</th>
              <th class="px-3 py-2 font-medium">关联 / 分账</th>
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
              <td class="px-3 py-2 text-muted-foreground">{{ x.paid_by || '—' }}</td>
              <td class="px-3 py-2 text-muted-foreground">{{ formatDate(x.occurred_at) }}</td>
              <td class="px-3 py-2 text-[11px] text-muted-foreground">
                <span v-if="dayName(x.day_id)" class="block">{{ dayName(x.day_id) }}</span>
                <span v-if="itemName(x.plan_item_id)" class="block">{{ itemName(x.plan_item_id) }}</span>
                <span class="block text-primary">{{ splitModeLabel(x.split_mode) }}</span>
              </td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap justify-end gap-1.5">
                  <Button variant="outline" size="sm" @click="openSplit(x)"><Users class="h-3.5 w-3.5" /> 分账</Button>
                  <Button variant="outline" size="sm" @click="openEdit(x)"><Pencil class="h-3.5 w-3.5" /> 编辑</Button>
                  <Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" @click="deleteTarget = x"><Trash2 class="h-3.5 w-3.5" /> 删除</Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- 新增 / 编辑费用 -->
    <Dialog v-model="dialogOpen" :title="editingId ? '编辑费用' : '记一笔费用'" width="max-w-lg">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="space-y-1"><label class="text-xs font-medium">分类</label><Select v-model="form.category" :options="categoryOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">金额</label><Input v-model="form.amount" type="number" step="0.01" placeholder="0.00" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">币种</label><Input v-model="form.currency" placeholder="例如：CNY" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">折算汇率</label><Input v-model="form.exchange_rate" type="number" step="any" placeholder="留空按 1.0" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">支付人（垫付人）</label><Input v-model="form.paid_by" placeholder="例如：成员 1" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">发生时间</label><Input v-model="form.occurred_at" type="datetime-local" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">所属行程日</label><Select v-model="form.day_id" :options="daySelectOptions" /></div>
        <div class="space-y-1"><label class="text-xs font-medium">关联地点</label><Select v-model="form.plan_item_id" :options="itemSelectOptions" /></div>
        <div class="space-y-1 sm:col-span-2"><label class="text-xs font-medium">分账方式</label><Select v-model="form.split_mode" :options="splitModeOptions" /></div>
        <div class="space-y-1 sm:col-span-2"><label class="text-xs font-medium">备注</label><Input v-model="form.note" placeholder="可选" /></div>
      </div>
      <p class="mt-2 text-[11px] text-muted-foreground">保存后会按所选方式自动生成分账明细；自定义份额、儿童免账与家庭分组可在列表点「分账」逐笔调整。</p>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="saving" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="saving" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /> 保存</Button>
      </template>
    </Dialog>

    <!-- 单笔费用分账设置 -->
    <Dialog v-model="splitOpen" title="设置单笔费用分账" :description="splitTarget ? `${categoryLabel(splitTarget.category)} · ${money(splitTarget.amount)}` : ''" width="max-w-lg">
      <div class="space-y-3">
        <div class="space-y-1"><label class="text-xs font-medium">分账方式</label><Select v-model="splitForm.split_mode" :options="splitModeOptions" /></div>
        <label class="flex min-h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="splitForm.child_free" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          儿童免账（勾选后儿童不承担费用）
        </label>
        <div class="space-y-1"><label class="text-xs font-medium">备注</label><Input v-model="splitForm.note" placeholder="可选，例如：这顿由三家平摊" /></div>

        <!-- 家庭成员分组与自定义份额 -->
        <div v-if="splitRows.length" class="space-y-1.5">
          <p class="text-xs font-medium">参与成员与家庭分组</p>
          <div class="overflow-hidden rounded-lg border border-border">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-border bg-muted/40 text-muted-foreground">
                <tr>
                  <th class="px-2.5 py-1.5 font-medium">成员</th>
                  <th class="px-2.5 py-1.5 font-medium">家庭分组</th>
                  <th v-if="splitForm.split_mode === 'custom'" class="px-2.5 py-1.5 font-medium">份额</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr v-for="r in splitRows" :key="r.id">
                  <td class="px-2.5 py-1.5">
                    {{ r.name }}
                    <span v-if="r.is_child" class="ml-1 text-[10px] text-muted-foreground">儿童</span>
                  </td>
                  <td class="px-2.5 py-1.5"><Input v-model="r.family" placeholder="例如：第一组" /></td>
                  <td v-if="splitForm.split_mode === 'custom'" class="px-2.5 py-1.5">
                    <Input v-model="r.share" type="number" min="0" step="any" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="text-[11px] text-muted-foreground">
            {{ splitForm.split_mode === 'custom' ? '份额为相对比例，按填写数值分摊本笔金额。' : '按家庭分组分摊时，相同分组视为一个家庭，家庭内成员再均分。' }}
          </p>
        </div>

        <!-- 保存后展示后端返回的份额明细 -->
        <div v-if="splitShares.length" class="space-y-1.5">
          <p class="text-xs font-medium">本笔分账明细</p>
          <div class="space-y-1">
            <div v-for="s in splitShares" :key="s.participant_id" class="flex items-center justify-between rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs">
              <span class="text-foreground">{{ participantName(s.participant_id) }}</span>
              <span class="font-medium text-primary">{{ money(s.amount) }}</span>
            </div>
          </div>
        </div>

        <p v-if="splitError" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ splitError }}</p>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="splitSaving" @click="splitOpen = false">关闭</Button>
        <Button size="sm" :disabled="splitSaving" @click="saveSplit"><Loader2 v-if="splitSaving" class="h-3.5 w-3.5 animate-spin" /> 保存分账</Button>
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
