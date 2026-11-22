<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Sparkles, X, Send } from 'lucide-vue-next'
import { postSSE } from '@/lib/api'

const route = useRoute()
const open = ref(false)
const input = ref('')
const messages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
const streaming = ref(false)

const context = computed(() => ({
  scope: route.name === 'trip-plan' ? 'plan' : 'global',
  trip_id: (route.params.tripId as string) || null,
  tab: String(route.name ?? ''),
  path: route.fullPath,
}))

function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  streaming.value = true
  let buffer = ''
  postSSE('/ai/chat', { message: text, ...context.value }, {
    onEvent: (event, data) => {
      if (event === 'delta') {
        const chunk = (data as { content?: string })?.content ?? ''
        buffer += chunk
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'assistant') last.content = buffer
        else messages.value.push({ role: 'assistant', content: buffer })
      } else if (event === 'error') {
        buffer += `\n[错误] ${(data as { message?: string })?.message ?? '请求失败'}`
      }
    },
    onDone: () => { streaming.value = false },
    onError: (err) => {
      messages.value.push({ role: 'assistant', content: `[连接失败] ${err.message}` })
      streaming.value = false
    },
  })
}
</script>

<template>
  <div class="fixed bottom-6 right-6 z-40">
    <div v-if="open" class="mb-3 flex h-[420px] w-[360px] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-lg">
      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <span class="flex items-center gap-2 text-sm font-medium"><Sparkles class="h-4 w-4 text-primary" /> 瞬旅 AI</span>
        <button class="text-muted-foreground hover:text-foreground" @click="open = false"><X class="h-4 w-4" /></button>
      </div>
      <div class="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        <p v-if="!messages.length" class="text-muted-foreground">问问行程安排、预算或想去的地方。</p>
        <div v-for="(m, i) in messages" :key="i" class="whitespace-pre-wrap rounded-lg px-3 py-2"
             :class="m.role === 'user' ? 'ml-8 bg-primary/10' : 'mr-8 bg-muted'">{{ m.content }}</div>
      </div>
      <div class="flex items-center gap-2 border-t border-border p-3">
        <input v-model="input" class="flex-1 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
               placeholder="输入问题…" @keydown.enter="send" />
        <button class="rounded-lg bg-primary p-2 text-primary-foreground disabled:opacity-50" :disabled="streaming || !input.trim()" @click="send">
          <Send class="h-4 w-4" />
        </button>
      </div>
    </div>
    <button class="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105"
            title="瞬旅 AI 助手" @click="open = !open">
      <Sparkles class="h-5 w-5" />
    </button>
  </div>
</template>
