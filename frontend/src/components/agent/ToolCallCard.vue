<script setup lang="ts">
/** 工具调用卡：只读工具直接展示结果；写类工具（needConfirm）展示「确认 / 取消」。
 *  确认由 AgentPanel 汇总后以 confirmToolCalls 回传 /ai/chat，后端执行时走同一套权限校验。
 *  删除行程为危险操作，按钮文案用「是 / 否」，并由 store 回传 confirm:"yes"。
 */
import { computed, ref } from 'vue'
import { Wrench, ShieldAlert, Check, X, Loader2, ChevronDown } from 'lucide-vue-next'
import { toolLabel, type ToolCall } from '@/stores/agent'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'

const props = withDefaults(defineProps<{ call: ToolCall; busy?: boolean }>(), { busy: false })
const emit = defineEmits<{ confirm: [call: ToolCall]; cancel: [call: ToolCall] }>()
const expanded = ref(false)

const label = computed(() => toolLabel(props.call.name))
const isDelete = computed(() => props.call.name === 'delete_trip')
const argsText = computed(() => JSON.stringify(props.call.arguments ?? {}, null, 2))
const resultText = computed(() => {
  const r = props.call.result
  if (r === undefined || r === null) return ''
  return typeof r === 'string' ? r : JSON.stringify(r, null, 2)
})
const waiting = computed(() => props.call.needConfirm && props.call.status === 'pending')
const statusLabel: Record<string, string> = {
  running: '执行中', pending: '待确认', done: '已完成', cancelled: '已取消', error: '失败',
}
</script>

<template>
  <div
    class="rounded-lg border px-2.5 py-2 text-[11px]"
    :class="waiting ? 'border-amber-300 bg-amber-50/70' : 'border-border bg-card'"
  >
    <div class="flex items-center gap-1.5">
      <Wrench class="h-3.5 w-3.5 shrink-0 text-primary" />
      <span class="font-medium text-foreground">{{ label }}</span>
      <code class="truncate text-[10px] text-muted-foreground">{{ call.name }}</code>
      <Badge
        class="ml-auto shrink-0"
        :variant="call.status === 'done' ? 'default' : call.status === 'cancelled' || call.status === 'error' ? 'destructive' : 'secondary'"
      >
        <Loader2 v-if="call.status === 'running'" class="mr-0.5 inline h-2.5 w-2.5 animate-spin" />
        {{ statusLabel[call.status] ?? call.status }}
      </Badge>
    </div>

    <p v-if="call.needConfirm" class="mt-1.5 flex items-start gap-1 text-amber-700">
      <ShieldAlert class="mt-0.5 h-3 w-3 shrink-0" />
      <span v-if="isDelete">删除行程不可恢复，请回答「是」确认；选择「否」即取消本次操作</span>
      <span v-else>{{ call.message || '该操作会修改行程数据，请确认后执行' }}</span>
      <span v-if="call.permission" class="font-mono text-[10px]">（{{ call.permission }}）</span>
    </p>

    <button
      class="mt-1 flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground"
      @click="expanded = !expanded"
    >
      <ChevronDown class="h-3 w-3 transition-transform" :class="expanded ? 'rotate-180' : ''" />
      {{ expanded ? '收起' : '查看参数' }}
    </button>
    <pre v-if="expanded" class="mt-1 max-h-40 overflow-auto rounded bg-muted p-2 text-[10px] leading-relaxed text-foreground">{{ argsText }}</pre>
    <pre v-if="expanded && resultText" class="mt-1 max-h-40 overflow-auto rounded bg-muted p-2 text-[10px] leading-relaxed text-foreground">{{ resultText }}</pre>

    <div v-if="waiting" class="mt-2 flex gap-1.5">
      <Button size="sm" class="h-7 px-2.5 text-[10px]" :disabled="busy" @click="emit('confirm', call)">
        <Check class="h-3 w-3" /> {{ isDelete ? '是' : '确认' }}
      </Button>
      <Button variant="outline" size="sm" class="h-7 px-2.5 text-[10px]" @click="emit('cancel', call)">
        <X class="h-3 w-3" /> {{ isDelete ? '否' : '取消' }}
      </Button>
    </div>
  </div>
</template>
