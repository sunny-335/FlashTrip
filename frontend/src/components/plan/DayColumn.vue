<script setup lang="ts">
/** 左栏的一天：Day 序号 / 日期 / 天气 / 标题编辑 / 折叠，内部为可跨组拖拽列表。 */
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
  editing.value = true
}

async function saveTitle() {
  try {
    await dnd.updateDay(props.day.id, { title: titleDraft.value })
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
        <div class="flex items-center gap-1.5">
          <span class="text-xs font-semibold">Day {{ day.day_index }}</span>
          <span class="text-[11px] text-muted-foreground">{{ formatDate(day.date) }}</span>
          <span v-if="weather" class="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground">
            <CloudSun class="h-3 w-3" /> {{ weather }}
          </span>
        </div>
        <div v-if="editing" class="mt-1 flex items-center gap-1">
          <Input v-model="titleDraft" class="h-7 text-xs" placeholder="当天标题" @keydown.enter="saveTitle" />
          <Button size="sm" class="h-7 px-2" @click="saveTitle">保存</Button>
          <Button variant="ghost" size="sm" class="h-7 px-2" @click="editing = false">取消</Button>
        </div>
        <p v-else-if="day.title" class="truncate text-[11px] text-muted-foreground">{{ day.title }}</p>
      </div>
      <button v-if="!editing" class="rounded-md p-1 text-muted-foreground hover:bg-muted" title="编辑标题" @click="startEdit">
        <Pencil class="h-3.5 w-3.5" />
      </button>
      <span class="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground">{{ list.length }}</span>
    </header>

    <div v-if="!day.collapsed" class="space-y-2 p-2">
      <VueDraggable
        v-model="list"
        :group="{ name: 'flashtrip-plan', pull: true, put: true }"
        :animation="120"
        :disabled="isMobile"
        item-key="id"
        :data-group="day.id"
        class="space-y-2"
        @end="onEnd"
      >
        <PlanCard v-for="(item, i) in list" :key="item.id" :item="item" :index="i" :count="list.length" />
      </VueDraggable>

      <p v-if="!list.length" class="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted-foreground">
        把右侧待规划池的条目拖到这里
      </p>
      <Button variant="ghost" size="sm" class="w-full" @click="openAdd('place', day.id)">
        <Plus class="h-3.5 w-3.5" /> 添加到 Day {{ day.day_index }}
      </Button>
      <p v-if="localError" class="text-[11px] text-destructive">{{ localError }}</p>
    </div>
  </section>
</template>
