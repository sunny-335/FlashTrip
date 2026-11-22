<script setup lang="ts">
/** 设置页：向导解锁、AI/地图 provider 配置、审图号、AI 工具开关、主题、主密钥备份说明。
 *  写 /settings 需先解锁（后端 _assert_unlocked），AI 工具开关走 /ai/tools/config（只需 ai:use）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Settings2, Sun, Moon, LockKeyhole, UnlockKeyhole, KeyRound, Bot,
  MapPinned, Save, Loader2, Copy, Check, RefreshCw, ShieldAlert,
} from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'
import { useUiStore } from '@/stores/ui'

interface AiProviderCfg {
  id: string
  base_url: string
  model: string
  enabled: boolean
  priority: number
  timeout_s: number
  has_api_key?: boolean
}
interface MapProviderCfg {
  id: string
  style_url: string
  tile_url_template: string
  default_style: string
  coord_system: string
  attribution: string
  audit_number: string
  enabled: boolean
  needs_token: boolean
  has_key?: boolean
}
interface SanitizedConfig {
  version?: string
  secret_key?: string
  ai?: { providers?: AiProviderCfg[] }
  map?: { providers?: MapProviderCfg[]; default_provider_id?: string; audit_number?: string }
  redis?: { url?: string; enabled?: boolean }
  security?: { ai_tools_enabled?: boolean }
}
interface ToolItem { name: string; description: string; write: boolean; permission: string | null; enabled: boolean }
interface ToolsConfig {
  enabled: boolean
  requiresConfirmation: boolean
  readTools: string[]
  writeTools: string[]
  tools: ToolItem[]
}

const ui = useUiStore()
const loading = ref(true)
const error = ref('')
const notice = ref('')
const version = ref('')

// 解锁
const unlocked = ref(false)
const unlockForm = reactive({ username: '', password: '' })
const unlocking = ref(false)
const unlockError = ref('')

// 配置
const auditNumber = ref('')
const defaultMapProviderId = ref('')
const aiDraft = ref<(AiProviderCfg & { api_key?: string })[]>([])
const mapDraft = ref<(MapProviderCfg & { key?: string })[]>([])
const savingConfig = ref(false)

// AI 工具
const tools = ref<ToolsConfig | null>(null)
const savingTools = ref(false)

// 主密钥轮换
const rotating = ref(false)
const newSecret = ref('')
const copiedSecret = ref(false)

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
    const [settings, status, toolCfg] = await Promise.all([
      api.get<{ version: string; config: SanitizedConfig }>('/settings'),
      api.get<{ unlocked: boolean }>('/wizard/status').catch(() => ({ unlocked: false })),
      api.get<ToolsConfig>('/ai/tools').catch(() => null),
    ])
    version.value = settings.version || settings.config?.version || ''
    const cfg = settings.config ?? {}
    auditNumber.value = cfg.map?.audit_number || ''
    defaultMapProviderId.value = cfg.map?.default_provider_id || ''
    aiDraft.value = (cfg.ai?.providers ?? []).map((p) => ({ ...p, api_key: '' }))
    mapDraft.value = (cfg.map?.providers ?? []).map((p) => ({ ...p, key: '' }))
    unlocked.value = Boolean(status.unlocked)
    tools.value = toolCfg
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
}

async function unlock() {
  if (!unlockForm.username.trim() || !unlockForm.password || unlocking.value) return
  unlocking.value = true
  unlockError.value = ''
  try {
    await api.post('/wizard/unlock', { username: unlockForm.username.trim(), password: unlockForm.password })
    unlocked.value = true
    unlockForm.password = ''
    flash('配置已解锁，现在可以保存设置')
  } catch (e) {
    unlockError.value = messageOf(e)
  } finally {
    unlocking.value = false
  }
}

/** 只提交非空字段；api_key / key 留空时后端保留原有密文，不会误清密钥。 */
async function saveConfig() {
  if (savingConfig.value) return
  if (!unlocked.value) { error.value = '配置已锁定，请先在上方用管理员密码解锁'; return }
  savingConfig.value = true
  error.value = ''
  try {
    const updated = await api.put<{ config?: SanitizedConfig } & SanitizedConfig>('/settings', {
      audit_number: auditNumber.value,
      map_default_provider_id: defaultMapProviderId.value,
      ai_providers: aiDraft.value.map((p) => ({
        id: p.id, base_url: p.base_url || '', api_key: p.api_key || '',
        model: p.model || '', enabled: p.enabled, priority: Number(p.priority) || 0,
        timeout_s: Number(p.timeout_s) || 60, supports_stream: true,
      })),
      map_providers: mapDraft.value.map((p) => ({
        id: p.id, key: p.key || '', style_url: p.style_url || '',
        tile_url_template: p.tile_url_template || '', default_style: p.default_style || '',
        coord_system: p.coord_system || 'WGS84', attribution: p.attribution || '',
        audit_number: p.audit_number || '', enabled: p.enabled, needs_token: p.needs_token,
      })),
    })
    const cfg = updated.config ?? updated
    if (cfg?.ai?.providers) aiDraft.value = cfg.ai.providers.map((p) => ({ ...p, api_key: '' }))
    if (cfg?.map?.providers) mapDraft.value = cfg.map.providers.map((p) => ({ ...p, key: '' }))
    flash('配置已保存')
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    savingConfig.value = false
  }
}

async function toggleTools() {
  if (!tools.value || savingTools.value) return
  const next = !tools.value.enabled
  savingTools.value = true
  error.value = ''
  try {
    tools.value = await api.put<ToolsConfig>('/ai/tools/config', { enabled: next })
    flash(next ? 'AI 工具已启用' : 'AI 工具已关闭')
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    savingTools.value = false
  }
}

async function toggleTool(name: string) {
  if (!tools.value || savingTools.value) return
  const current = tools.value.tools.find((t) => t.name === name)
  if (!current) return
  savingTools.value = true
  error.value = ''
  try {
    tools.value = await api.put<ToolsConfig>('/ai/tools/config', { tools: { [name]: !current.enabled } })
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    savingTools.value = false
  }
}

async function rotateSecret() {
  if (rotating.value) return
  rotating.value = true
  error.value = ''
  newSecret.value = ''
  try {
    const res = await api.post<{ rotated: boolean; need_backup_secret: boolean; secret_key: string }>('/settings/secret/rotate')
    newSecret.value = res.secret_key || ''
    flash('主密钥已轮换，请立即下载备份')
  } catch (e) {
    // 由环境变量提供密钥时后端会明确拒绝，原样展示
    error.value = messageOf(e)
  } finally {
    rotating.value = false
  }
}

async function copySecret() {
  if (!newSecret.value) return
  try {
    await navigator.clipboard.writeText(newSecret.value)
    copiedSecret.value = true
    window.setTimeout(() => { copiedSecret.value = false }, 1800)
  } catch { /* 用户可手动复制下方输入框 */ }
}

function downloadSecret() {
  if (!newSecret.value) return
  const blob = new Blob([newSecret.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'flashtrip-secret-key.txt'
  a.click()
  URL.revokeObjectURL(url)
}

const themeLabel = computed(() => ui.theme === 'dark' ? '深色' : '浅色')

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-[900px] space-y-5 px-5 py-6">
    <div>
      <h1 class="flex items-center gap-2 text-lg font-semibold"><Settings2 class="h-5 w-5 text-primary" /> 设置</h1>
      <p class="mt-0.5 text-xs text-muted-foreground">
        系统配置与偏好 <span v-if="version" class="ml-1 font-mono text-[10px]">v{{ version }}</span>
      </p>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <p v-if="notice" class="rounded-lg border border-primary/40 bg-accent/50 p-2.5 text-xs text-foreground">{{ notice }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在读取配置…</div>

    <template v-else>
      <!-- 主题 -->
      <Card>
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold">外观</h2>
            <p class="mt-0.5 text-xs text-muted-foreground">当前：{{ themeLabel }}；偏好存于本机浏览器。</p>
          </div>
          <div class="flex gap-1.5">
            <Button :variant="ui.theme === 'light' ? 'default' : 'outline'" size="sm" @click="ui.setTheme('light')">
              <Sun class="h-3.5 w-3.5" /> 浅色
            </Button>
            <Button :variant="ui.theme === 'dark' ? 'default' : 'outline'" size="sm" @click="ui.setTheme('dark')">
              <Moon class="h-3.5 w-3.5" /> 深色
            </Button>
          </div>
        </div>
      </Card>

      <!-- 解锁 -->
      <Card>
        <div class="mb-3 flex items-center justify-between">
          <h2 class="flex items-center gap-2 text-sm font-semibold">
            <LockKeyhole class="h-4 w-4 text-primary" /> 配置锁定
          </h2>
          <Badge :variant="unlocked ? 'default' : 'secondary'">
            {{ unlocked ? '已解锁' : '已锁定' }}
          </Badge>
        </div>
        <p v-if="!unlocked" class="mb-3 text-xs leading-relaxed text-muted-foreground">
          安装完成后配置被锁定。修改 AI / 地图供应商、审图号前，需用管理员账号解锁；解锁会写入审计记录。
        </p>
        <form v-if="!unlocked" class="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]" @submit.prevent="unlock">
          <Input v-model="unlockForm.username" placeholder="管理员用户名" autocomplete="username" />
          <Input v-model="unlockForm.password" type="password" placeholder="管理员密码" autocomplete="current-password" />
          <Button type="submit" size="sm" :disabled="unlocking || !unlockForm.username || !unlockForm.password">
            <Loader2 v-if="unlocking" class="h-3.5 w-3.5 animate-spin" />
            <UnlockKeyhole v-else class="h-3.5 w-3.5" /> 解锁
          </Button>
        </form>
        <p v-if="unlockError" class="mt-2 text-xs text-destructive">{{ unlockError }}</p>
        <p v-else class="mt-2 text-xs text-muted-foreground">应急解锁也可在服务器执行 <code class="font-mono">python -m app.cli wizard:unlock</code>。</p>
      </Card>

      <!-- 合规 / 审图号 -->
      <Card>
        <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold"><MapPinned class="h-4 w-4 text-primary" /> 地图与合规</h2>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1">
            <label class="text-xs font-medium">审图号</label>
            <Input v-model="auditNumber" placeholder="如 GS(2025)XXXX号" />
          </div>
          <div class="space-y-1">
            <label class="text-xs font-medium">默认底图 Provider ID</label>
            <Input v-model="defaultMapProviderId" placeholder="例如 openfreemap-liberty" />
          </div>
        </div>
        <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          境外底图（OpenFreeMap / OSM / Mapbox）无中国审图号，仅建议境外行程或个人自用；面向境内公众服务请配置带审图号的合规底图并完成备案，本系统不声称已完成地图合规备案。
        </p>
      </Card>

      <!-- AI / 地图 provider -->
      <Card>
        <div class="mb-3 flex items-center justify-between">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Bot class="h-4 w-4 text-primary" /> AI / 地图供应商</h2>
          <Button size="sm" :disabled="savingConfig || !unlocked" @click="saveConfig">
            <Loader2 v-if="savingConfig" class="h-3.5 w-3.5 animate-spin" />
            <Save v-else class="h-3.5 w-3.5" /> 保存配置
          </Button>
        </div>
        <p class="mb-3 rounded-md border border-amber-200 bg-amber-50/60 px-2.5 py-2 text-[11px] leading-relaxed text-amber-800">
          <ShieldAlert class="mr-1 inline h-3 w-3" />
          密钥经主密钥加密后仅存于服务端，前端永远拿不到明文（此处只显示「已配置」）。
          密钥输入框留空即保留原有密钥；模型名请通过探测或手填，不硬编码。
        </p>

        <h3 class="mb-2 text-xs font-semibold text-foreground">AI 供应商</h3>
        <div v-if="!aiDraft.length" class="mb-3 text-xs text-muted-foreground">未配置 AI 供应商。</div>
        <div v-for="p in aiDraft" :key="p.id" class="mb-2 rounded-lg border border-border bg-background p-2.5">
          <div class="mb-2 flex items-center gap-2">
            <span class="font-mono text-xs font-medium text-foreground">{{ p.id }}</span>
            <Badge :variant="p.has_api_key ? 'default' : 'outline'">{{ p.has_api_key ? '密钥已配置' : '未配置密钥' }}</Badge>
            <label class="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
              <input type="checkbox" v-model="p.enabled" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 启用
            </label>
          </div>
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Input v-model="p.base_url" placeholder="base_url（兼容 OpenAI /v1）" />
            <Input v-model="p.model" placeholder="模型名（动态 /models 或手填）" />
            <Input v-model="p.api_key" type="password" placeholder="新密钥（留空保留）" autocomplete="new-password" />
            <div class="grid grid-cols-2 gap-2">
              <Input v-model="p.priority" type="number" placeholder="优先级" />
              <Input v-model="p.timeout_s" type="number" placeholder="超时秒" />
            </div>
          </div>
        </div>

        <h3 class="mb-2 mt-4 text-xs font-semibold text-foreground">地图供应商</h3>
        <div v-if="!mapDraft.length" class="text-xs text-muted-foreground">未配置地图供应商。</div>
        <div v-for="p in mapDraft" :key="p.id" class="mb-2 rounded-lg border border-border bg-background p-2.5">
          <div class="mb-2 flex items-center gap-2">
            <span class="font-mono text-xs font-medium text-foreground">{{ p.id }}</span>
            <Badge :variant="p.has_key ? 'default' : 'outline'">{{ p.has_key ? '密钥已配置' : '未配置密钥' }}</Badge>
            <Badge variant="secondary">{{ p.coord_system }}</Badge>
            <label class="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
              <input type="checkbox" v-model="p.enabled" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 启用
            </label>
          </div>
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Input v-model="p.key" type="password" placeholder="新 key / token（留空保留）" autocomplete="new-password" />
            <Input v-model="p.style_url" placeholder="style URL（可选）" />
            <Input v-model="p.tile_url_template" placeholder="瓦片模板（可选）" />
            <Input v-model="p.coord_system" placeholder="坐标系 WGS84/GCJ02/BD09/CGCS2000" />
            <Input v-model="p.audit_number" placeholder="审图号（可选）" />
            <Input v-model="p.attribution" placeholder="attribution（必留）" />
          </div>
        </div>
      </Card>

      <!-- AI 工具 -->
      <Card>
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h2 class="flex items-center gap-2 text-sm font-semibold"><Bot class="h-4 w-4 text-primary" /> AI 工具</h2>
            <p class="mt-0.5 text-xs text-muted-foreground">只读工具默认可用；写类工具必须由对话卡片二次确认，并走同一套权限校验。</p>
          </div>
          <Button
            v-if="tools"
            :variant="tools.enabled ? 'default' : 'outline'"
            size="sm"
            :disabled="savingTools"
            @click="toggleTools"
          >{{ tools.enabled ? '已启用' : '已关闭' }}</Button>
        </div>
        <div v-if="tools" class="space-y-1.5">
          <label
            v-for="t in tools.tools"
            :key="t.name"
            class="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs"
          >
            <span class="min-w-0">
              <span class="block truncate font-medium text-foreground">{{ t.name }}</span>
              <span class="block truncate text-[10px] text-muted-foreground">{{ t.description }}</span>
            </span>
            <span class="flex shrink-0 items-center gap-2">
              <Badge :variant="t.write ? 'outline' : 'secondary'">{{ t.write ? `写 · 需确认${t.permission ? ` · ${t.permission}` : ''}` : '只读' }}</Badge>
              <input
                type="checkbox"
                class="h-3.5 w-3.5 accent-[var(--primary)]"
                :checked="t.enabled"
                :disabled="savingTools || !tools.enabled"
                @change="toggleTool(t.name)"
              />
            </span>
          </label>
          <p v-if="!tools.tools.length" class="text-xs text-muted-foreground">暂无工具定义。</p>
        </div>
        <p v-else class="text-xs text-muted-foreground">工具配置读取失败（可能缺少 ai:use 权限）。</p>
      </Card>

      <!-- 主密钥 -->
      <Card>
        <div class="mb-3 flex items-center justify-between">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><KeyRound class="h-4 w-4 text-primary" /> 主密钥</h2>
          <Button variant="outline" size="sm" :disabled="rotating" @click="rotateSecret">
            <Loader2 v-if="rotating" class="h-3.5 w-3.5 animate-spin" />
            <RefreshCw v-else class="h-3.5 w-3.5" /> 轮换
          </Button>
        </div>
        <div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs leading-relaxed text-foreground">
          <p class="flex items-center gap-1.5 font-medium text-destructive"><ShieldAlert class="h-3.5 w-3.5" /> 主密钥丢失的后果</p>
          <p class="mt-1.5 text-muted-foreground">
            主密钥用于加密所有 AI / 地图供应商密钥。一旦丢失且无备份，已加密的密钥将<b>无法解密</b>，
            必须在此重新填写全部供应商密钥；数据库里的行程数据本身不受影响。
            轮换会生成新密钥并用其重加密现有配置，轮换成功后<b>务必立即下载备份</b>并妥善离线保存。
            若主密钥由环境变量 <code class="font-mono">FLASHTRIP_SECRET_KEY</code> 提供，请直接更换该变量并重启。
          </p>
        </div>

        <div v-if="newSecret" class="mt-3 space-y-2">
          <p class="text-xs font-medium text-foreground">新主密钥（仅本次展示）</p>
          <Input :model-value="newSecret" readonly class="font-mono text-[11px]" />
          <div class="flex gap-2">
            <Button size="sm" @click="downloadSecret">下载备份</Button>
            <Button variant="outline" size="sm" @click="copySecret">
              <Check v-if="copiedSecret" class="h-3.5 w-3.5" /><Copy v-else class="h-3.5 w-3.5" />
              {{ copiedSecret ? '已复制' : '复制' }}
            </Button>
          </div>
        </div>
      </Card>
    </template>
  </div>
</template>
