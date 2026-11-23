<script setup lang="ts">
/**
 * 邮件通知：SMTP 配置（脱敏读写）、发送测试邮件、内置模板清单与最近发信记录。
 * 密码留空表示保留服务端密文；后端已提供内联样式的响应式中文模板，此处只展示说明。
 */
import { onMounted, reactive, ref } from 'vue'
import { Mail, Save, Loader2, Send, RefreshCw } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'

interface MailConfig {
  enabled: boolean
  host: string
  port: number
  user: string
  from_addr: string
  from_name: string
  use_ssl: boolean
  use_tls: boolean
  timeout_s: number
  default_recipients: string[]
  test_recipients: string[]
  has_password: boolean
}
interface MailTemplate { name: string; label: string; description: string }
interface MailLog {
  id: string
  to_addr: string
  subject: string
  template: string
  status: string
  error: string | null
  created_at: string
}

const form = reactive({
  enabled: false,
  host: '',
  port: 465,
  user: '',
  password: '',
  from_addr: '',
  from_name: '瞬旅 FlashTrip',
  use_ssl: true,
  use_tls: false,
  timeout_s: 10,
  recipientsText: '',
  testRecipientsText: '',
})
const hasPassword = ref(false)
const templates = ref<MailTemplate[]>([])
const logs = ref<MailLog[]>([])
const loading = ref(true)
const ready = ref(false)
const saving = ref(false)
const testing = ref(false)
const toast = useToastStore()

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function parseRecipients(text: string): string[] {
  return text.split(/[,，;；\n\s]+/).map((s) => s.trim()).filter(Boolean)
}
function buildPayload() {
  return {
    enabled: form.enabled,
    host: form.host.trim(),
    port: Number(form.port) || 465,
    user: form.user.trim(),
    password: form.password,
    from_addr: form.from_addr.trim(),
    from_name: form.from_name.trim(),
    use_ssl: form.use_ssl,
    use_tls: form.use_tls,
    timeout_s: Number(form.timeout_s) || 10,
    default_recipients: parseRecipients(form.recipientsText),
    test_recipients: parseRecipients(form.testRecipientsText),
  }
}

async function load() {
  loading.value = true
  try {
    const [cfg, tpl, logList] = await Promise.all([
      api.get<MailConfig>('/mail/config'),
      api.get<MailTemplate[]>('/mail/templates').catch(() => [] as MailTemplate[]),
      api.get<MailLog[]>('/mail/logs?limit=50').catch(() => [] as MailLog[]),
    ])
    form.enabled = Boolean(cfg.enabled)
    form.host = cfg.host || ''
    form.port = cfg.port || 465
    form.user = cfg.user || ''
    form.from_addr = cfg.from_addr || ''
    form.from_name = cfg.from_name || '瞬旅 FlashTrip'
    form.use_ssl = Boolean(cfg.use_ssl)
    form.use_tls = Boolean(cfg.use_tls)
    form.timeout_s = cfg.timeout_s || 10
    form.recipientsText = (cfg.default_recipients || []).join('\n')
    form.testRecipientsText = (cfg.test_recipients || []).join('\n')
    form.password = ''
    hasPassword.value = Boolean(cfg.has_password)
    templates.value = tpl
    logs.value = logList
    ready.value = true
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value || !ready.value) return
  saving.value = true
  try {
    await api.put('/mail/config', buildPayload())
    form.password = ''
    useToastStore().success('邮件配置已保存')
    await load()
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    saving.value = false
  }
}

/** 以当前表单作为临时配置直接测试，无需先保存。 */
async function sendTest() {
  if (testing.value || !ready.value) return
  testing.value = true
  try {
    const res = await api.post<{ ok: boolean; message: string }>('/mail/test', buildPayload())
    const message = res.message || (res.ok ? '测试邮件已发送' : '测试邮件发送失败')
    if (res.ok) toast.success(message)
    else toast.error(message)
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    testing.value = false
    await loadLogs()
  }
}

async function loadLogs() {
  try {
    logs.value = await api.get<MailLog[]>('/mail/logs?limit=50')
  } catch (e) {
    toast.error(messageOf(e))
  }
}

function templateLabel(name: string): string {
  return templates.value.find((t) => t.name === name)?.label || name
}
function formatTime(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">

    <!-- SMTP 配置 -->
    <Card class="space-y-3">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Mail class="h-4 w-4 text-primary" /> 邮件通知
          </h2>
          <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
            配置发信服务以发送出行提醒、协作邀请与分享通知。密码经加密后仅存于服务端，前端永不获取明文。
          </p>
        </div>
        <Button size="sm" :disabled="saving || loading || !ready" @click="save">
          <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
          <Save v-else class="h-3.5 w-3.5" /> 保存
        </Button>
      </div>

      <p v-if="loading" class="text-xs text-muted-foreground">正在读取邮件配置…</p>
      <Button v-else-if="!ready" variant="outline" size="sm" @click="load">重新读取邮件配置</Button>
      <template v-else>
        <label class="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-sm text-foreground">
          <input v-model="form.enabled" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          启用邮件通知
        </label>

        <div class="grid gap-2 sm:grid-cols-2">
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">服务器地址</label>
            <Input v-model="form.host" placeholder="发信服务器地址" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">端口</label>
            <Input v-model="form.port" type="number" placeholder="465" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">用户名</label>
            <Input v-model="form.user" placeholder="登录发信服务的用户名" autocomplete="username" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">密码</label>
            <Input v-model="form.password" type="password" placeholder="留空保留原密码" autocomplete="new-password" />
            <p class="text-[10px] text-muted-foreground">{{ hasPassword ? '服务端已保存密码' : '尚未保存密码' }}</p>
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">发件地址</label>
            <Input v-model="form.from_addr" placeholder="用于显示发件人的邮箱地址" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">发件人名称</label>
            <Input v-model="form.from_name" placeholder="瞬旅 FlashTrip" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">超时（秒）</label>
            <Input v-model="form.timeout_s" type="number" placeholder="10" />
          </div>
          <div class="flex items-end gap-3 pb-1">
            <label class="flex items-center gap-1.5 text-xs text-foreground">
              <input v-model="form.use_ssl" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 使用 SSL 加密
            </label>
            <label class="flex items-center gap-1.5 text-xs text-foreground">
              <input v-model="form.use_tls" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 使用 STARTTLS
            </label>
          </div>
          <div class="space-y-1 sm:col-span-2">
            <label class="text-[11px] text-muted-foreground">默认收件人（每行一个，或用逗号分隔）</label>
            <textarea
              v-model="form.recipientsText"
              rows="2"
              class="flex w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm outline-none transition placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="用于收取出游提醒等通知的邮箱"
            />
            <p class="text-[10px] leading-relaxed text-muted-foreground">
              SSL 与 STARTTLS 通常二选一；同时启用时优先使用 SSL。
            </p>
          </div>
          <div class="space-y-1 sm:col-span-2">
            <label class="text-[11px] text-muted-foreground">测试邮件收件人（留空则使用默认收件人）</label>
            <textarea v-model="form.testRecipientsText" rows="2" class="flex w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm outline-none transition focus-visible:ring-2 focus-visible:ring-ring" placeholder="指定测试邮件接收邮箱" />
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Button variant="outline" size="sm" :disabled="testing" @click="sendTest">
            <Loader2 v-if="testing" class="h-3.5 w-3.5 animate-spin" />
            <Send v-else class="h-3.5 w-3.5" /> 发送测试邮件
          </Button>
          <span class="text-[11px] text-muted-foreground">可直接用当前填写的内容测试，无需先保存。</span>
        </div>
      </template>
    </Card>

    <!-- 内置模板 -->
    <Card class="space-y-2">
      <h3 class="text-sm font-semibold text-foreground">内置邮件模板</h3>
      <p class="rounded-md border border-border bg-muted/40 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground">
        系统提供内联样式的响应式中文默认模板，适配手机与桌面阅读；所有说明与提示文案均为中文，无需另行编写英文内容。
      </p>
      <div v-if="templates.length" class="space-y-1.5">
        <div v-for="t in templates" :key="t.name" class="rounded-md border border-border bg-card px-2.5 py-2">
          <p class="text-xs font-medium text-foreground">{{ t.label }}</p>
          <p class="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{{ t.description }}</p>
        </div>
      </div>
      <p v-else class="text-xs text-muted-foreground">暂未获取到模板清单。</p>
    </Card>

    <!-- 最近发信记录 -->
    <Card class="space-y-2">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">最近发信记录</h3>
        <Button variant="ghost" size="sm" @click="loadLogs"><RefreshCw class="h-3.5 w-3.5" /> 刷新</Button>
      </div>
      <div v-if="logs.length" class="space-y-1.5">
        <div v-for="log in logs" :key="log.id" class="rounded-md border border-border bg-card px-2.5 py-2 text-xs">
          <div class="flex items-start justify-between gap-2">
            <span class="min-w-0">
              <span class="block truncate font-medium text-foreground">{{ log.subject || '（无主题）' }}</span>
              <span class="block truncate text-[11px] text-muted-foreground">
                收件人 {{ log.to_addr || '—' }} · {{ templateLabel(log.template) }} · {{ formatTime(log.created_at) }}
              </span>
              <span v-if="log.error" class="block truncate text-[11px] text-destructive">{{ log.error }}</span>
            </span>
            <Badge :variant="log.status === 'sent' ? 'default' : 'destructive'">
              {{ log.status === 'sent' ? '已发送' : '失败' }}
            </Badge>
          </div>
        </div>
      </div>
      <p v-else class="text-xs text-muted-foreground">暂无发信记录。</p>
    </Card>
  </div>
</template>
