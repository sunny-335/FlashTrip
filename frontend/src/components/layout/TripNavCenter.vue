<script setup lang="ts">
/** 行程页顶部导航：七 tab + 「当前行程设置」弹窗（基础信息 / 人数 / 家庭模式）与设为当前行程。
 *  弹窗仅 import ui/Dialog，不新建跨组组件；保存走 PUT /trips/{id}，
 *  设为当前走 PUT /trips/{id}/current。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Settings2, Check, Loader2, Trash2 } from 'lucide-vue-next'
import { api } from '@/lib/api'
import Dialog from '@/components/ui/Dialog.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Button from '@/components/ui/Button.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ShareDialog from '@/components/collab/ShareDialog.vue'
import { useToastStore } from '@/stores/toast'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()
const confirmDelete = ref(false)
const shareOpen = ref(false)
const tripId = computed(() => route.params.tripId as string)

const tabs = [
  { label: '行程', name: 'trip-plan' },
  { label: '预定', name: 'trip-bookings' },
  { label: '交通', name: 'trip-transports' },
  { label: '费用', name: 'trip-expenses' },
  { label: '物品', name: 'trip-packing' },
  { label: '瞬间', name: 'trip-moments' },
  { label: '协作', name: 'trip-collab' },
]

const statusOptions = [
  { value: 'planned', label: '计划中' },
  { value: 'ongoing', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已归档' },
]

interface TripForm {
  title: string
  destination: string
  start_date: string
  end_date: string
  status: string
  traveler_count: number | string
  has_children: boolean
  children_count: number | string
  family_mode: boolean
  family_name: string
}
interface DurationChange {
  preview?: boolean
  current_days?: number
  target_days?: number
  affected_items?: { id: string; title: string; from_day_index?: number }[]
  moved_items?: { id: string; title: string; from_day_index?: number }[]
}

const dialogOpen = ref(false)
const loading = ref(false)
const saving = ref(false)
const settingCurrent = ref(false)
const deleting = ref(false)
const currentSet = ref(false)
const formError = ref('')
const formNotice = ref('')
const durationChange = ref<DurationChange | null>(null)
const applyingShrink = ref(false)
const originalDates = ref({ start_date: '', end_date: '' })
const durationInput = ref('')
const durationDays = computed(() => {
  if (!form.start_date || !form.end_date || form.end_date < form.start_date) return ''
  return String(Math.floor((Date.parse(`${form.end_date}T00:00:00Z`) - Date.parse(`${form.start_date}T00:00:00Z`)) / 86400000) + 1)
})

const form = reactive<TripForm>({
  title: '', destination: '', start_date: '', end_date: '', status: 'planned',
  traveler_count: 1, has_children: false, children_count: 0, family_mode: false, family_name: '',
})
watch(() => [form.start_date, form.end_date], () => { durationChange.value = null })

async function openDialog() {
  dialogOpen.value = true
  formError.value = ''
  formNotice.value = ''
  currentSet.value = false
  loading.value = true
  try {
    const t = await api.get<Partial<TripForm>>(`/trips/${tripId.value}`)
    form.title = t.title ?? ''
    form.destination = t.destination ?? ''
    form.start_date = t.start_date ?? ''
    form.end_date = t.end_date ?? ''
    originalDates.value = { start_date: form.start_date, end_date: form.end_date }
    durationInput.value = ''
    form.status = t.status ?? 'planned'
    form.traveler_count = t.traveler_count ?? 1
    form.has_children = Boolean(t.has_children)
    form.children_count = t.children_count ?? 0
    form.family_mode = Boolean(t.family_mode)
    form.family_name = t.family_name ?? ''
  } catch (e) {
    formError.value = (e as Error)?.message || '行程信息读取失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

/** 人数校验：总数 ≥1；包含儿童时儿童数 ≥1 且严格小于总数。 */
function validate(): string {
  const total = Number(form.traveler_count)
  if (!form.title.trim()) return '标题不能为空'
  if (!Number.isInteger(total) || total < 1) return '出行人数至少为 1 人'
  if (form.has_children) {
    const children = Number(form.children_count)
    if (!Number.isInteger(children) || children < 1) return '包含儿童时，儿童人数至少为 1'
    if (children >= total) return '儿童人数必须小于出行总人数'
  }
  if (form.start_date && form.end_date && form.end_date < form.start_date) {
    return '结束日期不能早于开始日期'
  }
  return ''
}

async function save() {
  formError.value = ''
  formNotice.value = ''
  const problem = validate()
  if (problem) { formError.value = problem; return }
  saving.value = true
  try {
    const payload = {
      title: form.title.trim(),
      destination: form.destination.trim() || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      status: form.status,
      traveler_count: Number(form.traveler_count),
      has_children: form.has_children,
      children_count: form.has_children ? Number(form.children_count) : 0,
      family_mode: form.family_mode,
      family_name: form.family_name.trim() || null,
    }
    const result = await api.put<Partial<TripForm> & { duration_change?: DurationChange }>(`/trips/${tripId.value}`, payload)
    if (result.duration_change?.preview) {
      durationChange.value = result.duration_change
      formNotice.value = '缩短行程会将以下条目移入待规划区；确认后才会应用。'
      return
    }
    durationChange.value = null
    formNotice.value = '行程信息已保存'
    toast.success(formNotice.value)
  } catch (e) {
    formError.value = (e as Error)?.message || '保存失败，请稍后重试'
    toast.error(formError.value)
  } finally {
    saving.value = false
  }
}

function cancelShrinkPreview() {
  form.start_date = originalDates.value.start_date
  form.end_date = originalDates.value.end_date
  durationChange.value = null
  formNotice.value = ''
}

function formatDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function updateDuration(value: string) {
  durationInput.value = value
  const n = Number(value)
  if (!Number.isInteger(n) || n < 1) return
  if (form.start_date) {
    const end = new Date(`${form.start_date}T00:00:00`)
    end.setDate(end.getDate() + n - 1)
    form.end_date = formatDate(end)
  } else if (form.end_date) {
    const start = new Date(`${form.end_date}T00:00:00`)
    start.setDate(start.getDate() - n + 1)
    form.start_date = formatDate(start)
  }
}

async function confirmShrink() {
  if (!durationChange.value?.preview) return
  applyingShrink.value = true
  saving.value = true
  formError.value = ''
  try {
    const result = await api.put<Partial<TripForm> & { duration_change?: DurationChange }>(`/trips/${tripId.value}`, {
      title: form.title.trim(), destination: form.destination.trim() || null,
      start_date: form.start_date || null, end_date: form.end_date || null,
      status: form.status, traveler_count: Number(form.traveler_count), has_children: form.has_children,
      children_count: form.has_children ? Number(form.children_count) : 0,
      family_mode: form.family_mode, family_name: form.family_name.trim() || null,
      confirm_shrink: true,
    })
    durationChange.value = null
    originalDates.value = { start_date: form.start_date, end_date: form.end_date }
    formNotice.value = `已缩短行程，${result.duration_change?.moved_items?.length ?? 0} 个条目已移入待规划区。`
    toast.success(formNotice.value)
  } catch (e) {
    formError.value = (e as Error)?.message || '确认缩短行程失败'
  } finally {
    applyingShrink.value = false
    saving.value = false
  }
}

async function deleteTrip() {
  deleting.value = true
  try {
    await api.del(`/trips/${encodeURIComponent(tripId.value)}`)
    dialogOpen.value = false
    confirmDelete.value = false
    toast.success('行程已删除')
    await router.push('/trips')
  } catch (e) {
    formError.value = (e as Error)?.message || '删除失败，请稍后重试'
    toast.error(formError.value)
  } finally {
    deleting.value = false
  }
}

async function setCurrent() {
  settingCurrent.value = true
  formError.value = ''
  try {
    await api.put(`/trips/${tripId.value}/current`)
    currentSet.value = true
    formNotice.value = '已设为当前行程'
    toast.success(formNotice.value)
  } catch (e) {
    formError.value = (e as Error)?.message || '设置当前行程失败，请稍后重试'
    toast.error(formError.value)
  } finally {
    settingCurrent.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex h-full max-w-[1600px] items-center gap-2 px-3 sm:gap-4 sm:px-5">
    <button class="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground" @click="router.push('/trips')">
      <ArrowLeft class="h-4 w-4" /> <span class="hidden sm:inline">返回</span>
    </button>
    <!-- 七 tab 在窄屏横向滚动，不溢出 -->
    <nav class="nav-scroll flex min-w-0 flex-1 items-center gap-1 whitespace-nowrap">
      <RouterLink
        v-for="tab in tabs"
        :key="tab.name"
        :to="{ name: tab.name, params: { tripId } }"
        class="shrink-0 rounded-lg px-3 py-1.5 text-sm transition-colors"
        :class="route.name === tab.name
          ? 'bg-secondary font-medium text-foreground'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
      >{{ tab.label }}</RouterLink>
    </nav>
    <div class="shrink-0 flex items-center gap-1">
      <button class="rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted" @click="shareOpen = true">分享</button>
      <button
        class="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted sm:px-3"
        title="行程设置"
        @click="openDialog"
      >
        <Settings2 class="h-3.5 w-3.5" />
        <span>行程设置</span>
      </button>
    </div>
  </div>

  <ShareDialog v-model="shareOpen" :trip-id="tripId" @created="toast.success('分享链接已创建')" />
  <Dialog v-model="dialogOpen" title="行程设置" description="编辑行程基础信息与出行人群" width="max-w-lg">
    <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">
      <Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在读取行程信息…
    </div>
    <div v-else class="space-y-3">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="space-y-1">
          <span class="text-xs font-medium">标题</span>
          <Input v-model="form.title" placeholder="行程标题" />
        </label>
        <label class="space-y-1">
          <span class="text-xs font-medium">目的地</span>
          <Input v-model="form.destination" placeholder="例如：京都" />
        </label>
        <label class="space-y-1">
          <span class="text-xs font-medium">开始日期</span>
          <Input v-model="form.start_date" type="date" />
        </label>
        <label class="space-y-1">
          <span class="text-xs font-medium">结束日期</span>
          <Input v-model="form.end_date" type="date" />
        </label>
        <label class="space-y-1">
          <span class="text-xs font-medium">行程天数（含首尾）</span>
          <Input v-model="durationInput" type="number" min="1" placeholder="填写开始或结束日期后输入天数" @update:model-value="updateDuration(String($event))" />
        </label>
        <label class="space-y-1">
          <span class="text-xs font-medium">状态</span>
          <Select v-model="form.status" :options="statusOptions" />
        </label>
        <label class="space-y-1">
          <span class="text-xs font-medium">出行人数</span>
          <Input v-model="form.traveler_count" type="number" min="1" placeholder="至少 1 人" />
        </label>
      </div>

      <div class="rounded-lg border border-border bg-background p-3">
        <label class="flex items-center gap-2 text-xs font-medium">
          <input v-model="form.has_children" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          包含儿童
        </label>
        <label v-if="form.has_children" class="mt-2 block space-y-1">
          <span class="text-xs text-muted-foreground">儿童人数（至少 1 人且小于出行总人数）</span>
          <Input v-model="form.children_count" type="number" min="1" />
        </label>
      </div>

      <div class="rounded-lg border border-border bg-background p-3">
        <label class="flex items-center gap-2 text-xs font-medium">
          <input v-model="form.family_mode" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          家庭模式
        </label>
        <label v-if="form.family_mode" class="mt-2 block space-y-1">
          <span class="text-xs text-muted-foreground">家庭名称</span>
          <Input v-model="form.family_name" placeholder="例如：张家出游" />
        </label>
      </div>

      <p v-if="formError" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">{{ formError }}</p>
      <p v-if="formNotice" class="rounded-md border border-primary/40 bg-accent/50 px-2.5 py-1.5 text-xs text-foreground">{{ formNotice }}</p>
      <div v-if="durationChange?.preview" class="max-h-40 space-y-1 overflow-y-auto rounded-md border border-amber-300/60 bg-amber-50/60 p-2 text-xs">
        <p>行程天数将从 {{ durationChange.current_days }} 天缩短至 {{ durationChange.target_days }} 天；受影响条目将移入待规划区：</p>
        <ul class="list-disc pl-5"><li v-for="item in durationChange.affected_items" :key="item.id">第 {{ item.from_day_index }} 天 · {{ item.title }}</li><li v-if="!durationChange.affected_items?.length">没有受影响的条目</li></ul>
        <div class="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" :disabled="applyingShrink" @click="cancelShrinkPreview">取消并恢复日期</Button>
          <Button size="sm" :disabled="applyingShrink" @click="confirmShrink">{{ applyingShrink ? '正在应用…' : '确定并移入待规划区' }}</Button>
        </div>
      </div>
    </div>

    <template #footer>
      <Button variant="ghost" size="sm" class="mr-auto text-destructive" :disabled="deleting || loading" @click="confirmDelete = true"><Trash2 class="h-3.5 w-3.5" /> 删除行程</Button>
      <Button variant="outline" size="sm" @click="dialogOpen = false">取消</Button>
      <Button variant="outline" size="sm" :disabled="settingCurrent || loading" @click="setCurrent">
        <Check v-if="currentSet" class="h-3.5 w-3.5 text-primary" />
        <Settings2 v-else class="h-3.5 w-3.5" />
        {{ currentSet ? '已设为当前' : '设为当前行程' }}
      </Button>
      <Button size="sm" :disabled="saving || loading" @click="save">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        {{ saving ? '保存中…' : '保存修改' }}
      </Button>
    </template>
  </Dialog>
  <ConfirmDialog
    v-model="confirmDelete"
    title="删除行程"
    message="删除后行程及其内容将不再显示，确定继续吗？"
    confirm-text="删除行程"
    danger
    :busy="deleting"
    @confirm="deleteTrip"
  />
</template>
