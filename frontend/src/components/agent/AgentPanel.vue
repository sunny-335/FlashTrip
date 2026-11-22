<script setup lang="ts">
/** 完整对话面板：会话 + 流式输出 + 写工具二次确认。
 *  供全局 Agent FAB 复用；写工具确认后以 confirmToolCalls 回传 /ai/chat。
 */
import { computed, nextTick, ref } from 'vue'
import { Sparkles, Send, Square, RotateCcw, X, Bot } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import MessageBubble from './MessageBubble.vue'
import { useAgentContext } from '@/composables/useAgentContext'
import { useAgentStore, type ToolCall } from '@/stores/agent'

const props = withDefaults(defineProps<{ title?: string; compact?: boolean }>(), {
  title: '瞬旅 AI', compact: false,
})
const emit = defineEmits<{ close: [] }>()

const agent = useAgentStore()
const { context } = useAgentContext()
const input = ref('')
const scroller = ref<HTMLElement | null>(null)

const scopeLabel = computed(() => {
  switch (context.value.scope) {
    case 'plan': return '行程规划'
    case 'trip': return context.value.tab.replace('trip-', '') || '行程'
    default: return '全局'
  }
})

async function scrollToBottom() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

function send() {
  const text = input.value.trim()
  if (!text || agent.streaming) return
  input.value = ''
  agent.send(text, context.value)
  void scrollToBottom()
}

/** 单卡确认：把该调用交给 store，以 confirmToolCalls 回传后端执行。 */
function confirm(call: ToolCall) {
  agent.confirm([call], context.value)
  void scrollToBottom()
}
function confirmAll() {
  if (!agent.pendingCalls.length) return
  agent.confirm([...agent.pendingCalls], context.value)
  void scrollToBottom()
}
function cancel(call: ToolCall) {
  agent.cancel([call])
}
</script>

<template>
  <div class="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-lg"
       :class="compact ? 'h-full' : 'h-[460px] w-[380px]'">
    <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
      <div class="flex items-center gap-2 text-sm font-medium">
        <Sparkles class="h-4 w-4 text-primary" /> {{ props.title }}
        <span class="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">{{ scopeLabel }}</span>
      </div>
      <div class="flex items-center gap-1">
        <button class="rounded-md p-1 text-muted-foreground hover:bg-muted" title="新建会话" @click="agent.reset()">
          <RotateCcw class="h-3.5 w-3.5" />
        </button>
        <button class="rounded-md p-1 text-muted-foreground hover:bg-muted" title="关闭" @click="emit('close')">
          <X class="h-4 w-4" />
        </button>
      </div>
    </div>

    <div ref="scroller" class="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
      <div v-if="!agent.messages.length" class="grid h-full place-items-center text-center">
        <div class="text-muted-foreground">
          <Bot class="mx-auto mb-2 h-6 w-6" />
          <p class="text-xs">问问行程安排、预算或想去的地方。</p>
          <p v-if="context.summary" class="mt-1 max-w-[240px] text-[10px]">上下文：{{ context.summary }}</p>
        </div>
      </div>
      <MessageBubble
        v-for="m in agent.messages"
        :key="m.id"
        :message="m"
        :busy="agent.streaming"
        @confirm="confirm"
        @cancel="cancel"
      />
      <p v-if="agent.error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
        {{ agent.error }}
      </p>
    </div>

    <div v-if="agent.pendingCalls.length" class="flex items-center justify-between gap-2 border-t border-amber-200 bg-amber-50/60 px-3 py-2 text-[11px] text-amber-800">
      <span>{{ agent.pendingCalls.length }} 项写操作等待确认</span>
      <Button size="sm" class="h-7 px-2.5 text-[10px]" :disabled="agent.streaming" @click="confirmAll">全部确认</Button>
    </div>

    <div class="flex items-end gap-2 border-t border-border p-3">
      <textarea
        v-model="input"
        rows="2"
        class="max-h-24 flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
        placeholder="输入问题…（Enter 发送，Shift+Enter 换行）"
        @keydown.enter.exact.prevent="send"
      />
      <Button v-if="agent.streaming" variant="outline" size="sm" class="h-9 px-2.5" title="停止生成" @click="agent.stop()">
        <Square class="h-3.5 w-3.5" />
      </Button>
      <Button v-else size="sm" class="h-9 px-2.5" :disabled="!input.trim()" @click="send">
        <Send class="h-3.5 w-3.5" />
      </Button>
    </div>
  </div>
</template>
