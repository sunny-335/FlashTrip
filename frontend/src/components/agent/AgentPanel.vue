<script setup lang="ts">
/** 完整对话面板：会话列表 / 新建、/ai/models 动态模型选择、流式缓冲、停止生成、
 *  写工具二次确认，以及 GET /ai/tools 的全站可用操作清单（中文标签）。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { Sparkles, Send, Square, RotateCcw, X, Bot, Plus, Wrench, ChevronDown } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import MessageBubble from './MessageBubble.vue'
import { useAgentContext } from '@/composables/useAgentContext'
import { useAgentStore, toolLabel, type ToolCall } from '@/stores/agent'

const props = withDefaults(defineProps<{ title?: string; compact?: boolean }>(), {
  title: '瞬旅 AI', compact: false,
})
const emit = defineEmits<{ close: [] }>()

const agent = useAgentStore()
const { context } = useAgentContext()
const input = ref('')
const scroller = ref<HTMLElement | null>(null)

const conversationChoice = ref('')
const selectedProvider = ref('')
const selectedModel = ref('')
const loadingModels = ref(false)
const configError = ref('')

interface AiProvider { id: string; label: string; model: string; enabled: boolean; hasKey: boolean }
interface AiModel { id: string; ownedBy?: string }
interface ToolItem { name: string; description: string; write: boolean; permission: string | null; enabled: boolean }
interface ToolsConfig {
  enabled: boolean
  requiresConfirmation: boolean
  readTools: string[]
  writeTools: string[]
  tools: ToolItem[]
}

const providers = ref<AiProvider[]>([])
const modelOptions = ref<AiModel[]>([])
const tools = ref<ToolsConfig | null>(null)
const toolsOpen = ref(false)

const usableProviders = computed(() => providers.value.filter((p) => p.enabled && p.hasKey))

/** 页面范围标签统一中文，避免把路由标识当作可见文案。 */
const TAB_LABELS: Record<string, string> = {
  'trip-plan': '行程规划', 'trip-bookings': '预定', 'trip-transports': '交通',
  'trip-expenses': '费用', 'trip-packing': '物品', 'trip-moments': '瞬间', 'trip-collab': '协作',
  dashboard: '仪表盘', footprints: '足迹', memories: '记忆', trips: '行程', settings: '设置',
}
const scopeLabel = computed(() => {
  switch (context.value.scope) {
    case 'plan': return '行程规划'
    case 'trip': return TAB_LABELS[context.value.tab] ?? '行程'
    default: return '全局'
  }
})

async function scrollToBottom() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function loadProviders() {
  try { providers.value = await api.get<AiProvider[]>('/ai/providers') } catch { providers.value = [] }
}

async function loadTools() {
  try { tools.value = await api.get<ToolsConfig>('/ai/tools') } catch { tools.value = null }
}

/** 模型名来自运行时 /ai/models 探测，绝不硬编码。 */
async function onProviderChange() {
  modelOptions.value = []
  selectedModel.value = ''
  configError.value = ''
  agent.setModel(selectedProvider.value, '')
  if (!selectedProvider.value) return
  loadingModels.value = true
  try {
    modelOptions.value = await api.get<AiModel[]>(`/ai/models?provider=${encodeURIComponent(selectedProvider.value)}`)
    if (!modelOptions.value.length) configError.value = '该供应商暂未返回可用模型'
  } catch (e) {
    configError.value = e instanceof ApiError ? e.message : '模型列表读取失败，请稍后重试'
  } finally {
    loadingModels.value = false
  }
}

function onModelChange() {
  agent.setModel(selectedProvider.value, selectedModel.value)
}

async function onConversationChange() {
  if (conversationChoice.value) await agent.openConversation(conversationChoice.value)
  else agent.newConversation()
  await scrollToBottom()
}

async function newChat() {
  conversationChoice.value = ''
  agent.newConversation()
  await agent.loadConversations()
  await scrollToBottom()
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

onMounted(() => {
  void agent.loadConversations()
  void loadProviders()
  void loadTools()
})
</script>

<template>
  <div class="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-lg"
       :class="compact ? 'h-full w-full' : 'h-[460px] w-[380px]'">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
      <div class="flex items-center gap-2 text-sm font-medium">
        <Sparkles class="h-4 w-4 text-primary" /> {{ props.title }}
        <span class="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">{{ scopeLabel }}</span>
      </div>
      <div class="flex items-center gap-1">
        <button class="rounded-md p-1 text-muted-foreground hover:bg-muted" title="刷新会话列表" @click="agent.loadConversations()">
          <RotateCcw class="h-3.5 w-3.5" />
        </button>
        <button class="rounded-md p-1 text-muted-foreground hover:bg-muted" title="关闭" @click="emit('close')">
          <X class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- 会话 / 模型 / 操作工具条 -->
    <div class="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-1.5 text-[11px]">
      <select
        v-model="conversationChoice"
        class="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
        title="切换会话"
        @change="onConversationChange"
      >
        <option value="">当前对话</option>
        <option v-for="c in agent.conversations" :key="c.id" :value="c.id">{{ c.title || '未命名会话' }}</option>
      </select>
      <button class="inline-flex h-7 items-center gap-0.5 rounded-md border border-border px-2 text-muted-foreground hover:bg-muted" title="新建会话" @click="newChat">
        <Plus class="h-3 w-3" /> 新建
      </button>
      <select
        v-model="selectedProvider"
        class="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
        title="选择供应商"
        @change="onProviderChange"
      >
        <option value="">默认供应商</option>
        <option v-for="p in usableProviders" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
      <select
        v-model="selectedModel"
        class="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60"
        :disabled="!selectedProvider || loadingModels"
        title="选择模型"
        @change="onModelChange"
      >
        <option value="">{{ loadingModels ? '正在读取模型…' : selectedProvider ? '默认模型' : '先选供应商' }}</option>
        <option v-for="m in modelOptions" :key="m.id" :value="m.id">{{ m.id }}</option>
      </select>
      <button class="inline-flex h-7 items-center gap-0.5 rounded-md border border-border px-2 text-muted-foreground hover:bg-muted" :title="toolsOpen ? '收起可用操作' : '查看可用操作'" @click="toolsOpen = !toolsOpen">
        <Wrench class="h-3 w-3" /> 操作
        <span class="tabular-nums">{{ tools?.tools?.length ?? 0 }}</span>
        <ChevronDown class="h-3 w-3 transition-transform" :class="toolsOpen ? 'rotate-180' : ''" />
      </button>
    </div>

    <!-- 可用操作清单：中文标签，全站操作可见 -->
    <div v-if="toolsOpen" class="max-h-40 space-y-1 overflow-y-auto border-b border-border bg-muted/30 px-3 py-2 text-[11px]">
      <p v-if="!tools" class="text-muted-foreground">正在读取可用操作…</p>
      <p v-else-if="!tools.tools.length" class="text-muted-foreground">暂无可用操作。</p>
      <div v-for="t in tools.tools" :key="t.name" class="flex items-center gap-1.5 rounded-md bg-card px-2 py-1.5">
        <span class="shrink-0 font-medium text-foreground">{{ toolLabel(t.name) }}</span>
        <Badge class="shrink-0" :variant="t.write ? 'outline' : 'secondary'">{{ t.write ? '写入·需确认' : '只读' }}</Badge>
        <span v-if="!t.enabled" class="shrink-0 text-muted-foreground">已停用</span>
        <span class="ml-auto truncate text-right text-[10px] text-muted-foreground" :title="t.description">{{ t.description }}</span>
      </div>
      <p v-if="tools && !tools.enabled" class="text-amber-700">AI 工具已在设置中整体关闭。</p>
    </div>

    <p v-if="configError" class="border-b border-destructive/40 bg-destructive/5 px-3 py-1 text-[11px] text-destructive">{{ configError }}</p>

    <!-- 消息区 -->
    <div ref="scroller" class="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 text-sm">
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

    <!-- 待确认写工具 -->
    <div v-if="agent.pendingCalls.length" class="flex items-center justify-between gap-2 border-t border-amber-200 bg-amber-50/60 px-3 py-2 text-[11px] text-amber-800">
      <span>{{ agent.pendingCalls.length }} 项写操作等待确认</span>
      <Button size="sm" class="h-7 px-2.5 text-[10px]" :disabled="agent.streaming" @click="confirmAll">全部确认</Button>
    </div>

    <!-- 输入区 -->
    <div class="flex items-end gap-2 border-t border-border p-3">
      <textarea
        v-model="input"
        rows="2"
        class="max-h-24 min-h-0 flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
