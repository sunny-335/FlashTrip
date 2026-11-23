<script setup lang="ts">
/** 左栏的一天：第 N 天 / 日期 / 天气 / 标题编辑 / 折叠，内部为可跨组拖拽列表。
 *  空列表容器保持 min-h，空态提示 pointer-events-none 绝对铺满，让整块空白都可落点。
 */
import { computed, ref } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import { ChevronDown, ChevronRight, Pencil, Plus, CloudSun } from 'lucide-vue-next'
import { formatDate } from '@/lib/utils'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import PlanCard from './PlanCard.vue'
import { usePlanContext, type DragEndEvent } from '@/composables/usePlanDnd'
import type { PlanItem, TripDay } from '@/stores/plan'

const props = defineProps<{ day: TripDay }>()
const { dnd, isMobile, openAdd } = usePlanContext()

const editing = ref(false)
const titleDraft = ref('')
const dateDraft = ref(props.day.date ?? '')
const localError = ref('')

/** 可写计算属性：VueDraggable 的 v-model 直接写回 dnd.lists[day.id]。 */
const list = computed<PlanItem[]>({
  get: () => dnd.lists[props.day.id] ?? [],
  set: (v) => { dnd.lists[props.day.id] = v },
})

const weather = computed(() => {
  const raw = props.day.weather_json
  if (!raw) return ''
  try {
    const w = JSON.parse(raw) as Record<string, unknown>
    return [w.text ?? w.condition ?? w.desc, w.temp ?? w.temperature].filter(Boolean).map(String).join(' ')
  } catch {
    return raw
  }
})

function onEnd(evt: DragEndEvent) {
  void dnd.onEnd(evt)
}

function startEdit() {
  titleDraft.value = props.day.title ?? ''
  dateDraft.value = props.day.date ?? ''
  editing.value = true
}

async function saveTitle() {
  try {
    await dnd.updateDay(props.day.id, { title: titleDraft.value, date: dateDraft.value || null })
    editing.value = false
    localError.value = ''
  } catch (e) {
    localError.value = (e as Error).message
  }
}

async function toggleCollapse() {
  try {
    await dnd.updateDay(props.day.id, { collapsed: !props.day.collapsed })
    localError.value = ''
  } catch (e) {
    localError.value = (e as Error).message
  }
}
</script>

<template>
  <section class="rounded-lg border border-border bg-muted/30">
    <header class="flex items-center gap-2 border-b border-border px-3 py-2">
      <button class="rounded-md p-0.5 text-muted-foreground hover:bg-muted" :title="day.collapsed ? '展开' : '折叠'" @click="toggleCollapse">
        <ChevronDown v-if="!day.collapsed" class="h-3.5 w-3.5" />
        <ChevronRight v-else class="h-3.5 w-3.5" />
      </button>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <!-- 横杠只在有标题时拼接，无标题时只显示「第 N 天」+ 日期 -->
          <span class="text-xs font-semibold">
            第 {{ day.day_index }} 天<span v-if="day.title"> — {{ day.title }}</span>
          </span>
          <span v-if="day.date" class="text-[11px] text-muted-foreground">{{ formatDate(day.date) }}</span>
          <span v-if="weather" class="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground">
            <CloudSun class="h-3 w-3" /> {{ weather }}
          </span>
        </div>
        <div v-if="editing" class="mt-1 flex flex-wrap items-center gap-1">
          <Input v-model="titleDraft" class="h-7 min-w-24 flex-1 text-xs" placeholder="当天标题" @keydown.enter="saveTitle" />
          <Input v-model="dateDraft" type="date" class="h-7 w-36 text-xs" @keydown.enter="saveTitle" />
          <Button size="sm" class="h-7 px-2" @click="saveTitle">保存</Button>
          <Button variant="ghost" size="sm" class="h-7 px-2" @click="editing = false">取消</Button>
        </div>
      </div>
      <button v-if="!editing" class="rounded-md p-1 text-muted-foreground hover:bg-muted" title="编辑标题" @click="startEdit">
        <Pencil class="h-3.5 w-3.5" />
      </button>
      <span class="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground">{{ list.length }}</span>
    </header>

    <div v-if="!day.collapsed" class="space-y-2 p-2">
      <!-- 相对包裹层：容器有明确最小高度，空态提示不拦截指针，整块空白都可放置 -->
      <div class="relative">
        <VueDraggable
          v-model="list"
          :group="{ name: 'flashtrip-plan', pull: true, put: true }"
          :animation="120"
          :disabled="isMobile"
          item-key="id"
          :data-group="day.id"
          class="relative min-h-[120px] space-y-2"
          @start="dnd.onStartDrag"
          @end="onEnd"
        >
          <PlanCard v-for="(item, i) in list" :key="item.id" :item="item" :index="i" :count="list.length" />
        </VueDraggable>
        <div
          v-if="!list.length"
          class="pointer-events-none absolute inset-0 flex items-center justify-center rounded-lg border border-dashed border-border px-3 text-center text-[11px] text-muted-foreground"
        >
          拖拽到此地
        </div>
      </div>
      <Button variant="ghost" size="sm" class="w-full" @click="openAdd('place', day.id)">
        <Plus class="h-3.5 w-3.5" /> 添加到第 {{ day.day_index }} 天
      </Button>
      <p v-if="localError" class="text-[11px] text-destructive">{{ localError }}</p>
    </div>
  </section>
</template>
