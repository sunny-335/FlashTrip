<script setup lang="ts">
/**
 * 人工智能分区：供应商（接口地址 / 模型 / 密钥 / 启用）与 AI 工具总开关。
 * 统一保存 PUT /settings 的 { ai_providers, ai_tools_enabled }；
 * 密钥留空表示保留服务端密文，模型名由探测或手填，不硬编码。
 */
import { onMounted, ref } from 'vue'
import { Bot, Save, Loader2, Plus, Trash2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'

interface AiProviderCfg {
  id: string
  base_url: string
  model: string
  enabled: boolean
  priority: number
  timeout_s: number
  has_api_key?: boolean
}
interface AiDraft extends AiProviderCfg {
  api_key: string
}
interface SettingsView {
  config?: {
    ai?: { providers?: AiProviderCfg[] }
    security?: { ai_tools_enabled?: boolean }
  }
  ai?: { providers?: AiProviderCfg[] }
  security?: { ai_tools_enabled?: boolean }
}
interface ToolItem { name: string; description: string; write: boolean }
interface ToolsConfig { enabled: boolean; tools: ToolItem[] }

const draft = ref<AiDraft[]>([])
const aiToolsEnabled = ref(false)
const tools = ref<ToolsConfig | null>(null)
const loading = ref(true)
const saving = ref(false)
const notice = ref('')
const error = ref('')

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function flash(text: string) {
  notice.value = text
  window.setTimeout(() => { notice.value = '' }, 2600)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [settings, toolCfg] = await Promise.all([
      api.get<SettingsView>('/settings'),
      api.get<ToolsConfig>('/ai/tools').catch(() => null),
    ])
    const list = settings.config?.ai?.providers ?? settings.ai?.providers ?? []
    draft.value = list.map((p) => ({ ...p, api_key: '' }))
    aiToolsEnabled.value = Boolean(
      settings.config?.security?.ai_tools_enabled ?? settings.security?.ai_tools_enabled,
    )
    tools.value = toolCfg
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
}

function addProvider() {
  draft.value.push({
    id: '', base_url: '', model: '', enabled: true,
    priority: 0, timeout_s: 60, api_key: '',
  })
}
function removeProvider(index: number) {
  draft.value.splice(index, 1)
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    await api.put('/settings', {
      ai_providers: draft.value
        .filter((p) => p.id.trim())
        .map((p) => ({
          id: p.id.trim(),
          base_url: p.base_url || '',
          api_key: p.api_key || '',
          model: p.model || '',
          enabled: p.enabled,
          priority: Number(p.priority) || 0,
          timeout_s: Number(p.timeout_s) || 60,
          supports_stream: true,
        })),
      ai_tools_enabled: aiToolsEnabled.value,
    })
    flash('人工智能配置已保存')
    await load()
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <Card class="space-y-4">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Bot class="h-4 w-4 text-primary" /> 人工智能
        </h2>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
          配置兼容 OpenAI 接口的供应商与模型名。密钥经主密钥加密后仅存于服务端，前端永不获取明文；
          密钥输入框留空即保留原有密钥。
        </p>
      </div>
      <Button size="sm" :disabled="saving || loading" @click="save">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        <Save v-else class="h-3.5 w-3.5" /> 保存
      </Button>
    </div>

    <p v-if="loading" class="text-xs text-muted-foreground">正在读取供应商配置…</p>
    <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ error }}</p>
    <p v-if="notice" class="rounded-md border border-primary/40 bg-accent px-2.5 py-2 text-xs text-accent-foreground">{{ notice }}</p>

    <template v-if="!loading">
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-xs font-semibold text-foreground">供应商与模型</h3>
          <Button variant="outline" size="sm" @click="addProvider"><Plus class="h-3.5 w-3.5" /> 新增供应商</Button>
        </div>
        <p v-if="!draft.length" class="text-xs text-muted-foreground">暂未配置供应商，可点击「新增供应商」添加。</p>

        <div v-for="(p, i) in draft" :key="i" class="space-y-2 rounded-lg border border-border bg-background p-3">
          <div class="flex items-center gap-2">
            <span class="text-xs font-medium text-foreground">供应商 {{ i + 1 }}</span>
            <Badge :variant="p.has_api_key ? 'default' : 'outline'">
              {{ p.has_api_key ? '密钥已配置' : '未配置密钥' }}
            </Badge>
            <label class="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
              <input v-model="p.enabled" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 启用
            </label>
            <button
              type="button"
              class="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
              title="移除该供应商"
              @click="removeProvider(i)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
          <div class="grid gap-2 sm:grid-cols-2">
            <div class="space-y-1">
              <label class="text-[11px] text-muted-foreground">供应商标识</label>
              <Input v-model="p.id" placeholder="自定义标识" />
            </div>
            <div class="space-y-1">
              <label class="text-[11px] text-muted-foreground">模型名</label>
              <Input v-model="p.model" placeholder="由服务商控制台或探测结果给出" />
            </div>
            <div class="space-y-1 sm:col-span-2">
              <label class="text-[11px] text-muted-foreground">接口地址</label>
              <Input v-model="p.base_url" placeholder="兼容 OpenAI /v1 的接口地址" />
            </div>
            <div class="space-y-1">
              <label class="text-[11px] text-muted-foreground">新密钥</label>
              <Input v-model="p.api_key" type="password" placeholder="留空保留原密钥" autocomplete="new-password" />
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div class="space-y-1">
                <label class="text-[11px] text-muted-foreground">优先级</label>
                <Input v-model="p.priority" type="number" placeholder="0" />
              </div>
              <div class="space-y-1">
                <label class="text-[11px] text-muted-foreground">超时（秒）</label>
                <Input v-model="p.timeout_s" type="number" placeholder="60" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="space-y-2 border-t border-border pt-3">
        <label class="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-sm text-foreground">
          <input v-model="aiToolsEnabled" type="checkbox" class="mt-0.5 h-4 w-4 accent-[var(--primary)]" />
          <span>
            启用 AI 工具
            <span class="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">
              只读工具默认可用；写类操作仍需在对话卡片中二次确认，并经过同一套权限校验。
            </span>
          </span>
        </label>
        <div v-if="tools?.tools?.length" class="space-y-1">
          <p class="text-[11px] text-muted-foreground">当前可用工具</p>
          <div v-for="t in tools.tools" :key="t.name" class="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs">
            <span class="min-w-0">
              <span class="block truncate font-medium text-foreground">{{ t.name }}</span>
              <span class="block truncate text-[10px] text-muted-foreground">{{ t.description }}</span>
            </span>
            <Badge :variant="t.write ? 'outline' : 'secondary'">{{ t.write ? '写操作需确认' : '只读' }}</Badge>
          </div>
        </div>
      </div>
    </template>
  </Card>
</template>
