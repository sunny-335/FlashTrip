<script setup lang="ts">
/** 右栏待规划池：All / Unplanned 筛选、搜索、分类、添加与导入入口，及可跨组拖拽列表。 */
import { computed, ref } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import { Plus, Search, Upload, ListPlus, Building2, Plane, MapPin, Route } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import PlanCard from './PlanCard.vue'
import { POOL_KEY, usePlanContext, type DragEndEvent } from '@/composables/usePlanDnd'
import type { PlanItem } from '@/stores/plan'

const { dnd, isMobile, openAdd, openImport } = usePlanContext()

const scope = ref<'unplanned' | 'all'>('unplanned')
const search = ref('')
// 用 string 存储以匹配原生 select / ui-Select 的 v-model:string
const category = ref('all')
const scopes = [
  { k: 'all', t: 'All' },
  { k: 'unplanned', t: 'Unplanned' },
] as const

const TYPE_LABEL: Record<string, string> = {
  place: '地点', hotel: '酒店', transport: '交通', activity: '活动', note: '备注',
}
const categoryOptions = [
  { value: 'all', label: '全部分类' },
  { value: 'place', label: '地点' },
  { value: 'activity', label: '活动' },
  { value: 'hotel', label: '酒店' },
  { value: 'transport', label: '交通' },
  { value: 'note', label: '备注' },
]

const list = computed<PlanItem[]>({
  get: () => dnd.lists[POOL_KEY] ?? [],
  set: (v) => { dnd.lists[POOL_KEY] = v },
})

const hasFilter = computed(() => Boolean(search.value.trim()) || category.value !== 'all')

/** 只读展示用；应用了筛选时禁用拖拽，避免打乱 sort_key 邻居计算。 */
const displayList = computed(() => {
  const base = scope.value === 'all' ? dnd.allItems.value : list.value
  const q = search.value.trim().toLowerCase()
  return base.filter((i) => {
    if (category.value !== 'all' && i.type !== category.value) return false
    if (!q) return true
    return [i.title, i.subtitle, i.address, i.category]
      .some((v) => (v ?? '').toLowerCase().includes(q))
  })
})

function dayLabel(item: PlanItem): string {
  if (!item.day_id) return '待规划池'
  const d = dnd.days.value.find((x) => x.id === item.day_id)
  return d ? `Day ${d.day_index}` : '已排入某天'
}

function onEnd(evt: DragEndEvent) {
  void dnd.onEnd(evt)
}
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-muted/30">
    <header class="border-b border-border px-3 py-2">
      <div class="flex items-center justify-between">
        <h2 class="text-xs font-semibold">待规划池</h2>
        <span class="text-[11px] text-muted-foreground">{{ list.length }} 条待排</span>
      </div>
      <div class="mt-2 inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
        <button
          v-for="s in scopes"
          :key="s.k"
          class="rounded-md px-2.5 py-1 text-[11px]"
          :class="scope === s.k ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted'"
          @click="scope = s.k"
        >{{ s.t }}</button>
      </div>
    </header>

    <div class="space-y-2 border-b border-border p-3">
      <div class="relative">
        <Search class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input v-model="search" class="pl-8" placeholder="搜索标题 / 地址 / 分类" />
      </div>
      <Select v-model="category" :options="categoryOptions" />
      <div class="grid grid-cols-2 gap-1.5">
        <Button variant="outline" size="sm" @click="openAdd('place')"><MapPin class="h-3.5 w-3.5" /> Add Place</Button>
        <Button variant="outline" size="sm" @click="openAdd('activity')"><Route class="h-3.5 w-3.5" /> Add Activity</Button>
        <Button variant="outline" size="sm" @click="openAdd('hotel')"><Building2 class="h-3.5 w-3.5" /> 酒店</Button>
        <Button variant="outline" size="sm" @click="openAdd('transport')"><Plane class="h-3.5 w-3.5" /> 交通</Button>
        <Button variant="ghost" size="sm" @click="openImport('file')"><Upload class="h-3.5 w-3.5" /> Import file</Button>
        <Button variant="ghost" size="sm" @click="openImport('list')"><ListPlus class="h-3.5 w-3.5" /> List Import</Button>
      </div>
      <p v-if="hasFilter" class="text-[11px] text-muted-foreground">筛选结果仅供查看，清除筛选后可拖拽排序。</p>
    </div>

    <div class="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
      <!-- 无筛选 + Unplanned：可拖拽 -->
      <VueDraggable
        v-if="scope === 'unplanned' && !hasFilter"
        v-model="list"
        :group="{ name: 'flashtrip-plan', pull: true, put: true }"
        :animation="120"
        :disabled="isMobile"
        item-key="id"
        :data-group="POOL_KEY"
        class="space-y-2"
        @end="onEnd"
      >
        <PlanCard v-for="(item, i) in list" :key="item.id" :item="item" :index="i" :count="list.length" />
      </VueDraggable>

      <!-- 筛选 / All：只读展示 -->
      <template v-else>
        <div v-for="item in displayList" :key="item.id" class="rounded-lg border border-border bg-card p-2.5">
          <div class="flex items-start justify-between gap-1.5">
            <p class="truncate text-xs font-medium">{{ item.title }}</p>
            <Badge variant="secondary">{{ TYPE_LABEL[item.type] ?? item.type }}</Badge>
          </div>
          <p class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ item.address || item.subtitle || dayLabel(item) }}</p>
          <p v-if="scope === 'all'" class="mt-0.5 text-[11px] text-muted-foreground">{{ dayLabel(item) }}</p>
        </div>
        <p v-if="!displayList.length" class="rounded-lg border border-dashed border-border px-3 py-6 text-center text-[11px] text-muted-foreground">
          没有匹配的条目
        </p>
      </template>

      <div v-if="scope === 'unplanned' && !hasFilter && !list.length" class="rounded-lg border border-dashed border-border px-3 py-6 text-center text-[11px] text-muted-foreground">
        池子空了。点上方 Add Place，或用 Import 批量导入清单。
      </div>
      <Button v-if="scope === 'unplanned' && !hasFilter" variant="ghost" size="sm" class="w-full" @click="openAdd('place')">
        <Plus class="h-3.5 w-3.5" /> 添加地点
      </Button>
    </div>
  </div>
</template>
