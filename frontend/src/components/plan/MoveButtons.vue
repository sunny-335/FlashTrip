<script setup lang="ts">
/** 移动端（≤768px）排序按钮：上移 / 下移 / 移至某天或待规划池。 */
import { computed, ref } from 'vue'
import { ChevronUp, ChevronDown } from 'lucide-vue-next'
import { formatDate } from '@/lib/utils'
import { POOL_KEY, usePlanContext } from '@/composables/usePlanDnd'

const props = defineProps<{ itemId: string; index: number; count: number }>()
const { dnd } = usePlanContext()

const target = ref('')
const options = computed(() => [
  ...dnd.days.value.map((d) => ({
    value: d.id,
    label: `第 ${d.day_index} 天${d.date ? ` · ${formatDate(d.date)}` : ''}`,
  })),
  { value: POOL_KEY, label: '待规划池' },
])

function onSelect() {
  if (!target.value) return
  void dnd.moveByButton(props.itemId, { kind: 'to', toKey: target.value })
  target.value = ''
}
</script>

<template>
  <div class="flex items-center gap-1.5">
    <button
      class="inline-flex h-7 items-center gap-0.5 rounded-md border border-border px-2 text-[11px] text-muted-foreground hover:bg-muted disabled:opacity-40"
      :disabled="index <= 0"
      @click="dnd.moveByButton(itemId, { kind: 'up' })"
    ><ChevronUp class="h-3 w-3" /> 上移</button>
    <button
      class="inline-flex h-7 items-center gap-0.5 rounded-md border border-border px-2 text-[11px] text-muted-foreground hover:bg-muted disabled:opacity-40"
      :disabled="index >= count - 1"
      @click="dnd.moveByButton(itemId, { kind: 'down' })"
    ><ChevronDown class="h-3 w-3" /> 下移</button>
    <select
      v-model="target"
      class="ml-auto h-7 max-w-[9rem] rounded-md border border-input bg-card px-1.5 text-[11px] text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
      @change="onSelect"
    >
      <option value="">移至某天</option>
      <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>
  </div>
</template>
