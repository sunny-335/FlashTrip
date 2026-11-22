<script setup lang="ts">
/** 行程新建 / 编辑表单：基本信息 + 参加人数、儿童、家庭模式。
 *  字段对齐后端 TripCreate / TripUpdate，提交到 POST /trips 或 PUT /trips/{id}。
 *  新建时 tripId 为空；编辑时按 tripId 读取 GET /trips/{id} 回填。
 */
import { reactive, ref, watch } from 'vue'
import { Users, Baby, Home, Loader2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Dialog from '@/components/ui/Dialog.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'

/** 行程返回体（含人数 / 家庭字段），字段对齐后端 TripOut。 */
export interface TripRecord {
  id: string
  title: string
  destination: string | null
  start_date: string | null
  end_date: string | null
  cover_url: string | null
  status: string
  traveler_count: number
  has_children: boolean
  children_count: number
  family_mode: boolean
  family_name: string | null
}

const props = defineProps<{ tripId?: string }>()
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [trip: TripRecord, created: boolean] }>()

const statusOptions = [
  { value: 'planned', label: '计划中' },
  { value: 'ongoing', label: '进行中' },
  { value: 'completed', label: '已完成' },
]

interface FormState {
  title: string
  destination: string
  start_date: string
  end_date: string
  status: string
  traveler_count: number
  has_children: boolean
  children_count: number
  family_mode: boolean
  family_name: string
}

function emptyForm(): FormState {
  return {
    title: '', destination: '', start_date: '', end_date: '', status: 'planned',
    traveler_count: 1, has_children: false, children_count: 0,
    family_mode: false, family_name: '',
  }
}

const form = reactive<FormState>(emptyForm())
const saving = ref(false)
const loading = ref(false)
const error = ref('')

const isEdit = () => Boolean(props.tripId)
const title = () => (isEdit() ? '编辑行程' : '新建行程')

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败，请稍后重试'
}

/** 打开时重置或读取编辑数据；每次打开都清空上一轮的错误。 */
watch(open, async (v) => {
  if (!v) return
  error.value = ''
  Object.assign(form, emptyForm())
  if (!props.tripId) return
  loading.value = true
  try {
    const t = await api.get<TripRecord>(`/trips/${encodeURIComponent(props.tripId)}`)
    Object.assign(form, {
      title: t.title || '',
      destination: t.destination || '',
      start_date: t.start_date || '',
      end_date: t.end_date || '',
      status: t.status || 'planned',
      traveler_count: Number(t.traveler_count) || 1,
      has_children: Boolean(t.has_children),
      children_count: Number(t.children_count) || 0,
      family_mode: Boolean(t.family_mode),
      family_name: t.family_name || '',
    })
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
})

/** 前端先按后端同口径校验，避免提交后才报错。 */
function validate(): string {
  if (!form.title.trim()) return '请填写行程标题'
  const total = Number(form.traveler_count)
  if (!Number.isInteger(total) || total < 1) return '参加人数不得少于 1 人'
  if (form.has_children) {
    const children = Number(form.children_count)
    if (!Number.isInteger(children) || children < 1) return '包含儿童时，儿童人数至少为 1 人'
    if (children >= total) return '儿童人数必须小于参加总人数'
  }
  return ''
}

function payload() {
  const total = Number(form.traveler_count) || 1
  // 未勾选儿童时强制归零，与后端 normalize_people 保持一致
  const children = form.has_children ? Number(form.children_count) || 0 : 0
  return {
    title: form.title.trim(),
    destination: form.destination.trim() || null,
    start_date: form.start_date || null,
    end_date: form.end_date || null,
    status: form.status,
    traveler_count: total,
    has_children: form.has_children,
    children_count: children,
    family_mode: form.family_mode,
    family_name: form.family_mode ? (form.family_name.trim() || null) : null,
  }
}

async function submit() {
  if (saving.value || loading.value) return
  const invalid = validate()
  if (invalid) { error.value = invalid; return }
  saving.value = true
  error.value = ''
  try {
    const created = !isEdit()
    const trip = created
      ? await api.post<TripRecord>('/trips', payload())
      : await api.put<TripRecord>(`/trips/${encodeURIComponent(props.tripId!)}`, payload())
    open.value = false
    emit('saved', trip, created)
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog v-model="open" :title="title()" :description="isEdit() ? '修改行程基本信息与参加人群' : '先填基本信息，创建后即可进入三栏规划页'" width="max-w-lg">
    <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">
      <Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在读取行程信息…
    </div>

    <form v-else class="space-y-4" @submit.prevent="submit">
      <!-- 基本信息 -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="space-y-1.5 sm:col-span-2">
          <label class="text-xs font-medium">标题 <span class="text-destructive">*</span></label>
          <Input v-model="form.title" placeholder="例如：五一去成都" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">目的地</label>
          <Input v-model="form.destination" placeholder="例如：成都" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">状态</label>
          <Select v-model="form.status" :options="statusOptions" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">开始日期</label>
          <Input v-model="form.start_date" type="date" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">结束日期</label>
          <Input v-model="form.end_date" type="date" />
        </div>
      </div>

      <!-- 参加人群 -->
      <div class="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
        <div class="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <Users class="h-3.5 w-3.5 text-primary" /> 参加人群
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <label class="text-xs font-medium">参加人数 <span class="text-destructive">*</span></label>
            <Input v-model="form.traveler_count" type="number" min="1" step="1" />
            <p class="text-[11px] text-muted-foreground">含成人与儿童，至少 1 人</p>
          </div>
          <div class="flex flex-col justify-center gap-2 pt-4">
            <label class="flex min-h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs text-foreground">
              <input v-model="form.has_children" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
              <Baby class="h-3.5 w-3.5 text-primary" /> 包含儿童
            </label>
          </div>
          <div v-if="form.has_children" class="space-y-1.5 sm:col-span-2">
            <label class="text-xs font-medium">儿童人数</label>
            <Input v-model="form.children_count" type="number" min="1" :max="Math.max(1, Number(form.traveler_count) - 1)" step="1" />
            <p class="text-[11px] text-muted-foreground">至少 1 人，且须小于参加总人数（{{ form.traveler_count }} 人）</p>
          </div>
        </div>
      </div>

      <!-- 家庭模式 -->
      <div class="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
        <div class="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <Home class="h-3.5 w-3.5 text-primary" /> 家庭模式
        </div>
        <label class="flex min-h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="form.family_mode" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          按家庭分组分账
        </label>
        <div v-if="form.family_mode" class="space-y-1.5">
          <label class="text-xs font-medium">家庭名称</label>
          <Input v-model="form.family_name" placeholder="例如：张家出游" />
          <p class="text-[11px] text-muted-foreground">用于费用按家庭分摊时标识本家庭</p>
        </div>
      </div>

      <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">
        {{ error }}
      </p>
    </form>

    <template #footer>
      <Button variant="outline" size="sm" :disabled="saving" @click="open = false">取消</Button>
      <Button size="sm" :disabled="saving || loading" @click="submit">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        {{ saving ? '保存中…' : (isEdit() ? '保存修改' : '创建并规划') }}
      </Button>
    </template>
  </Dialog>
</template>
