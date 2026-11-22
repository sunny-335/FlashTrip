<script setup lang="ts">
/** 计划卡片：三栏列表的共同子项。根元素带 data-id 供 Sortable @end 识别被拖条目。 */
import { computed, ref } from 'vue'
import { GripVertical, Trash2, Clock3, MapPin } from 'lucide-vue-next'
import Badge from '@/components/ui/Badge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import MoveButtons from './MoveButtons.vue'
import { usePlanContext } from '@/composables/usePlanDnd'
import type { PlanItem } from '@/stores/plan'

const props = defineProps<{ item: PlanItem; index: number; count: number }>()
const { isMobile, remove } = usePlanContext()
const confirmOpen = ref(false)

const TYPE_LABEL: Record<string, string> = {
  place: '地点', hotel: '酒店', transport: '交通', activity: '活动', note: '备注',
}

const timeLabel = computed(() => {
  const raw = props.item.start_time
  if (!raw) return ''
  const d = new Date(raw)
  return Number.isNaN(d.getTime())
    ? raw
    : d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
})

function doDelete() {
  confirmOpen.value = false
  remove(props.item.id)
}
</script>

<template>
  <div
    :data-id="item.id"
    class="group rounded-lg border border-border bg-card p-2.5 shadow-sm transition hover:border-primary/40"
  >
    <div class="flex items-start gap-1.5">
      <GripVertical class="mt-0.5 h-3.5 w-3.5 shrink-0 cursor-grab text-muted-foreground/60" />
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
          <span v-if="timeLabel" class="inline-flex items-center gap-0.5"><Clock3 class="h-3 w-3" /> {{ timeLabel }}</span>
          <span v-if="item.category">{{ item.category }}</span>
        </div>
      </div>
      <button
        class="shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition hover:bg-muted hover:text-destructive group-hover:opacity-100"
        title="删除"
        @click.stop="confirmOpen = true"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </button>
    </div>

    <!-- 移动端：禁用 Sortable 时改渲染上下/移至某天按钮 -->
    <MoveButtons v-if="isMobile" :item-id="item.id" :index="index" :count="count" class="mt-2 border-t border-border pt-2" />

    <ConfirmDialog
      v-model="confirmOpen"
      title="删除条目"
      :message="`确定删除「${item.title}」吗？删除后不可在本页恢复。`"
      confirm-text="删除"
      danger
      @confirm="doDelete"
    />
  </div>
</template>
