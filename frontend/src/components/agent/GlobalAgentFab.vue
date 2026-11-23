<script setup lang="ts">
/** 全局 AI 悬浮入口：按钮永久固定在右下角，开合只控制独立面板节点的显隐。 */
import { ref } from 'vue'
import { Sparkles, X } from 'lucide-vue-next'
import AgentPanel from './AgentPanel.vue'

const open = ref(false)
</script>

<template>
  <!-- 按钮位置恒定，不随面板开合变化 -->
  <button
    class="fixed right-6 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 bottom-6 [@media(max-width:768px)]:bottom-[calc(5rem+var(--safe-bottom))]"
    title="瞬旅 AI 助手"
    :aria-expanded="open"
    aria-label="开关瞬旅 AI 助手"
    @click="open = !open"
  >
    <X v-if="open" class="h-5 w-5" />
    <Sparkles v-else class="h-5 w-5" />
  </button>

  <!-- 面板作为独立兄弟节点，从右下角展开 -->
  <div
    v-if="open"
    class="agent-panel fixed bottom-20 right-6 z-40 w-[min(380px,calc(100vw-3rem))]"
  >
    <AgentPanel compact @close="open = false" />
  </div>
</template>
