<script setup lang="ts">
/** 对话气泡：user / assistant / tool；流式消息显示光标；工具调用交给 ToolCallCard。 */
import { Sparkles, UserRound } from 'lucide-vue-next'
import type { ChatMessage, ToolCall } from '@/stores/agent'
import ToolCallCard from './ToolCallCard.vue'
import MarkdownText from '@/components/common/MarkdownText.vue'

defineProps<{ message: ChatMessage; busy?: boolean }>()
const emit = defineEmits<{
  confirm: [call: ToolCall]
  cancel: [call: ToolCall]
}>()
</script>

<template>
  <div class="flex gap-2" :class="message.role === 'user' ? 'flex-row-reverse' : ''">
    <span
      class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
      :class="message.role === 'user' ? 'bg-secondary text-muted-foreground' : 'bg-primary/10 text-primary'"
    >
      <UserRound v-if="message.role === 'user'" class="h-3.5 w-3.5" />
      <Sparkles v-else class="h-3.5 w-3.5" />
    </span>
    <div class="min-w-0 max-w-[86%] space-y-1.5">
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
      <ToolCallCard
        v-for="call in message.toolCalls ?? []"
        :key="call.toolCallId"
        :call="call"
        :busy="busy"
        @confirm="emit('confirm', $event)"
        @cancel="emit('cancel', $event)"
      />
    </div>
  </div>
</template>
