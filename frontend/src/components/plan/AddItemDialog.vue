<script setup lang="ts">
/** 新增条目对话框：字段对齐 PlanItemCreate；sort_key 由前端 keyBetween 追加到目标分组末尾。 */
import { computed, reactive, ref, watch } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import { keyBetween } from '@/lib/sortKey'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Dialog from '@/components/ui/Dialog.vue'
import { POOL_KEY, usePlanContext } from '@/composables/usePlanDnd'
import type { PlanItemCreate, PlanType } from '@/stores/plan'

const props = withDefaults(
  defineProps<{ defaultType?: PlanType; defaultDayId?: string | null }>(),
  { defaultType: 'place', defaultDayId: null },
)
const open = defineModel<boolean>({ default: false })
const { dnd } = usePlanContext()

const form = reactive({
  type: 'place',
  title: '',
  subtitle: '',
  address: '',
  category: '',
  start_time: '',
  duration_min: '',
  note: '',
  day_id: '',
})
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
  ...dnd.days.value.map((d) => ({ value: d.id, label: `Day ${d.day_index}` })),
])

watch(open, (v) => {
  if (!v) return
  form.type = props.defaultType
  form.day_id = props.defaultDayId ?? ''
  form.title = ''
  form.subtitle = ''
  form.address = ''
  form.category = ''
  form.start_time = ''
  form.duration_min = ''
  form.note = ''
  error.value = ''
})

/** 目标分组末尾追加：保证 sort_key 始终是合法 fractional key，避免落入后端 next_sort_key 的 ...z 键。 */
function endSortKey(): string {
  const targetKey = form.day_id || POOL_KEY
  const existing = dnd.lists[targetKey] ?? []
  const last = existing.length ? existing[existing.length - 1].sort_key : null
  return keyBetween(last, null)
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
    category: form.category.trim() || null,
    start_time: form.start_time || null,
    duration_min: form.duration_min ? Number(form.duration_min) : null,
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
        <label class="text-xs font-medium">标题 <span class="text-destructive">*</span></label>
        <Input v-model="form.title" placeholder="例如：灵隐寺" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">副标题</label>
        <Input v-model="form.subtitle" placeholder="可选" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">地址</label>
        <Input v-model="form.address" placeholder="可选" />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">分类</label>
          <Input v-model="form.category" placeholder="例如：景点" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">时长（分钟）</label>
          <Input v-model="form.duration_min" type="number" placeholder="可选" />
        </div>
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">开始时间</label>
        <Input v-model="form.start_time" type="datetime-local" />
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
