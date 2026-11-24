<script setup lang="ts">
/**
 * 对话气泡：user / assistant / tool；流式消息显示光标。
 * 助手消息的「思考与工具调用」折叠成一条摘要行，显示在正文结果「上方」，
 * 默认收起，点击才展开明细；待确认的写操作始终展开可见，避免用户漏确认。
 */
import { computed, ref } from 'vue'
import { Sparkles, UserRound, ChevronDown, Brain, Wrench } from 'lucide-vue-next'
import type { ChatMessage, ToolCall } from '@/stores/agent'
import ToolCallCard from './ToolCallCard.vue'
import MarkdownText from '@/components/common/MarkdownText.vue'

const props = defineProps<{ message: ChatMessage; busy?: boolean }>()
const emit = defineEmits<{
  confirm: [call: ToolCall]
  cancel: [call: ToolCall]
}>()

const expanded = ref(false)

const calls = computed(() => props.message.toolCalls ?? [])
/** 有待确认的写操作时必须展开，否则用户看不到确认入口。 */
const hasPending = computed(() => calls.value.some((c) => c.needConfirm && c.status === 'pending'))
const collapsed = computed(() => calls.value.length > 0 && !expanded.value && !hasPending.value)
const summary = computed(() => {
  const n = calls.value.length
  const pending = calls.value.filter((c) => c.needConfirm && c.status === 'pending').length
  if (pending) return `${pending} 项操作待确认`
  return `思考与工具调用 · ${n} 步`
})
</script>

<template>
  <!-- 历史里的 tool 行只承载工具返回值，结果已并入上方工具卡片，不再单独成气泡 -->
  <div v-if="message.role !== 'tool'" class="flex gap-2" :class="message.role === 'user' ? 'flex-row-reverse' : ''">
    <span
      class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
      :class="message.role === 'user' ? 'bg-secondary text-muted-foreground' : 'bg-primary/10 text-primary'"
    >
      <UserRound v-if="message.role === 'user'" class="h-3.5 w-3.5" />
      <Sparkles v-else class="h-3.5 w-3.5" />
    </span>
    <div class="min-w-0 max-w-[86%] space-y-1.5">
      <!-- 思考与工具调用：位于结果上方，默认收起 -->
      <div
        v-if="calls.length"
        class="rounded-lg border border-border bg-card/70 text-[11px] text-muted-foreground"
      >
        <button
          class="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left hover:text-foreground"
          :class="hasPending ? 'cursor-default' : 'cursor-pointer'"
          :aria-expanded="expanded"
          @click="hasPending ? undefined : (expanded = !expanded)"
        >
          <Brain class="h-3.5 w-3.5 shrink-0 text-primary" />
          <span class="truncate">{{ summary }}</span>
          <Wrench v-if="!hasPending" class="h-3 w-3 shrink-0 opacity-60" />
          <ChevronDown
            v-if="!hasPending"
            class="ml-auto h-3 w-3 shrink-0 transition-transform"
            :class="expanded ? 'rotate-180' : ''"
          />
        </button>
        <div v-if="!collapsed" class="space-y-1.5 border-t border-border p-2">
          <ToolCallCard
            v-for="call in calls"
            :key="call.toolCallId"
            :call="call"
            :busy="busy"
            @confirm="emit('confirm', $event)"
            @cancel="emit('cancel', $event)"
          />
        </div>
      </div>

      <div
        class="break-words rounded-lg px-3 py-2 text-xs leading-relaxed"
        :class="message.role === 'user'
          ? 'bg-primary/10 text-foreground whitespace-pre-wrap'
          : 'border border-border bg-muted/50 text-foreground'"
      >
        <span v-if="message.role === 'user' && message.content">{{ message.content }}</span>
        <MarkdownText v-else-if="message.role === 'assistant' && message.content" :source="message.content" compact />
        <span v-if="message.streaming" class="ml-0.5 inline-block h-3 w-1 animate-pulse rounded-sm bg-primary align-middle" />
        <span v-if="!message.content && !message.streaming" class="text-muted-foreground">（空）</span>
      </div>
    </div>
  </div>
</template>
