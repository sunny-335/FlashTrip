<script setup lang="ts">
/** 计划卡片：三栏列表的共同子项。根元素带 data-id 供 Sortable @end 识别被拖条目。
 *  整卡点击打开「修改行程条目」弹窗（拖拽中不误触发）；编辑 / 删除都走真实后端 API。
 *  时间区可单独点击触发「重排」；命中冲突时时间文字标红并显示「时间冲突」徽标。
 */
import { computed, ref } from 'vue'
import { GripVertical, Trash2, Pencil, Clock3, MapPin, Loader2 } from 'lucide-vue-next'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import MoveButtons from './MoveButtons.vue'
import { usePlanContext } from '@/composables/usePlanDnd'
import { usePlanStore, type PlanItem } from '@/stores/plan'
import { clockOfIso, formatDuration } from '@/lib/time'

const props = defineProps<{ item: PlanItem; index: number; count: number }>()
const { dnd, isMobile, remove, openEdit, openRearrange } = usePlanContext()
const store = usePlanStore()
const confirmOpen = ref(false)

const editing = ref(false)
const editTitle = ref('')
const editAddress = ref('')
const editNote = ref('')
const editError = ref('')
const saving = ref(false)

const TYPE_LABEL: Record<string, string> = {
  place: '地点', hotel: '酒店', transport: '交通', activity: '活动', note: '备注',
}

/** 该条目是否命中 GET /plan/conflicts 返回的冲突集合。 */
const conflicted = computed(() => store.conflictIds.has(props.item.id))

const startClock = computed(() => clockOfIso(props.item.start_time))
const endClock = computed(() => clockOfIso(props.item.end_time))
const durationLabel = computed(() =>
  props.item.duration_min == null ? '' : formatDuration(props.item.duration_min),
)
/** 时间显示：起止范围 + 2h10m 形式的时长；130 分钟显示为 2h10m。 */
const timeLabel = computed(() => {
  const s = startClock.value
  const e = endClock.value
  const d = durationLabel.value
  if (!s && !e && !d) return ''
  const range = s && e ? `${s}–${e}` : s || e || ''
  return d ? `${range} · ${d}` : range
})

function doDelete() {
  confirmOpen.value = false
  remove(props.item.id)
}

/** 整卡点击打开完整修改弹窗；拖拽刚结束时的补发 click 直接忽略。 */
function onCardClick() {
  if (dnd.wasJustDragged()) return
  openEdit(props.item)
}

function startEdit() {
  editTitle.value = props.item.title
  editAddress.value = props.item.address ?? ''
  editNote.value = props.item.note ?? ''
  editError.value = ''
  editing.value = true
}

async function saveEdit() {
  if (!editTitle.value.trim()) {
    editError.value = '请填写标题'
    return
  }
  editError.value = ''
  saving.value = true
  try {
    await dnd.updateItem(props.item.id, {
      title: editTitle.value.trim(),
      address: editAddress.value.trim() || null,
      note: editNote.value.trim() || null,
    })
    editing.value = false
  } catch (e) {
    editError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div
    :data-id="item.id"
    class="group cursor-pointer rounded-lg border border-border bg-card p-2.5 shadow-sm transition hover:border-primary/40"
    :class="conflicted ? 'border-red-300' : ''"
    @click="onCardClick"
  >
    <div class="flex items-start gap-1.5">
      <GripVertical v-if="!isMobile" class="mt-0.5 h-3.5 w-3.5 shrink-0 cursor-grab text-muted-foreground/60" />
      <div class="min-w-0 flex-1">
        <div class="flex items-start justify-between gap-1.5">
          <p class="truncate text-xs font-medium text-foreground">{{ item.title }}</p>
          <Badge variant="secondary">{{ TYPE_LABEL[item.type] ?? item.type }}</Badge>
        </div>
        <p v-if="item.subtitle" class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ item.subtitle }}</p>
        <div class="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[11px] text-muted-foreground">
          <span v-if="item.address" class="inline-flex max-w-full items-center gap-0.5 truncate">
            <MapPin class="h-3 w-3 shrink-0" /> {{ item.address }}
          </span>
          <!-- 时间区可单独点击触发重排；命中冲突时文字标红 + 「时间冲突」徽标 -->
          <button
            v-if="timeLabel || conflicted"
            type="button"
            class="-mx-1 inline-flex items-center gap-1 rounded-md px-1 py-0.5 transition hover:bg-muted"
            :class="conflicted ? 'text-red-600' : 'text-muted-foreground'"
            title="点击重排该天时间，消除冲突"
            @click.stop="openRearrange(item)"
          >
            <Clock3 class="h-3 w-3" />
            <span>{{ timeLabel || '时间' }}</span>
            <Badge v-if="conflicted" variant="destructive" class="px-1 py-0 text-[10px] leading-tight">时间冲突</Badge>
          </button>
          <span v-if="item.category">{{ item.category }}</span>
          <span v-if="item.note" class="truncate">{{ item.note }}</span>
        </div>
      </div>
      <div class="flex shrink-0 items-center gap-0.5">
        <!-- 移动端没有 hover，按钮常显；PC 端 hover 时浮现 -->
        <button
          class="rounded-md p-1 text-muted-foreground hover:bg-muted"
          :class="isMobile ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
          title="快速编辑"
          @click.stop="startEdit"
        >
          <Pencil class="h-3.5 w-3.5" />
        </button>
        <button
          class="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
          :class="isMobile ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
          title="删除"
          @click.stop="confirmOpen = true"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    <!-- 内联快速编辑：提交后真实 PUT 落库；完整字段请点卡片打开修改弹窗 -->
    <div v-if="editing" class="mt-2 space-y-1.5 border-t border-border pt-2" @click.stop>
      <Input v-model="editTitle" class="h-8 text-xs" placeholder="标题" />
      <Input v-model="editAddress" class="h-8 text-xs" placeholder="地址（可选）" />
      <Input v-model="editNote" class="h-8 text-xs" placeholder="备注（可选）" />
      <p v-if="editError" class="text-[11px] text-destructive">{{ editError }}</p>
      <div class="flex justify-end gap-1.5">
        <Button variant="ghost" size="sm" class="h-7 px-2" :disabled="saving" @click.stop="editing = false">取消</Button>
        <Button size="sm" class="h-7 px-2" :disabled="saving" @click.stop="saveEdit">
          <Loader2 v-if="saving" class="h-3 w-3 animate-spin" /> 保存
        </Button>
      </div>
    </div>

    <!-- 移动端：禁用 Sortable 时改渲染上下 / 移至某天按钮，外层阻止冒泡以免误开弹窗 -->
    <div v-if="isMobile" @click.stop>
      <MoveButtons :item-id="item.id" :index="index" :count="count" class="mt-2 border-t border-border pt-2" />
    </div>

    <ConfirmDialog
      v-model="confirmOpen"
      title="删除条目"
      :message="`确定删除「${item.title}」吗？删除后不可在本页恢复。`"
      confirm-text="是"
      cancel-text="否"
      danger
      @confirm="doDelete"
    />
  </div>
</template>
