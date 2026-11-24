<script setup lang="ts">
/**
 * 第 5 步（新增）：邮件通知，可跳过。
 * 跳过时 mail_skipped=true，向导直接放行；不跳过时校验服务器地址与发件地址。
 * 「发送测试邮件」调 POST /wizard/test-mail；安装完成后仍可在设置页继续配置。
 */
import { computed, ref, watch } from 'vue'
import { Mail, Send, Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import {
  createMailConfig, useConfigStore,
  type InstallIn, type MailConfigIn, type WizardProbe,
} from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const cfg = useConfigStore()

// 表单对象始终存在：createInstallForm 已初始化，此处再兜底一次，便于模板直接双向绑定
if (!props.form.mail) props.form.mail = createMailConfig()
const mail = props.form.mail as MailConfigIn

const testing = ref(false)
const testOk = ref<boolean | null>(null)
const testResult = ref('')

const recipientsText = ref(mail.default_recipients.join('\n'))
// 文本框内容实时同步回配置，避免依赖失焦或点击测试按钮才生效
watch(recipientsText, (v) => {
  mail.default_recipients = v.split(/[,，;；\n\s]+/).map((s) => s.trim()).filter(Boolean)
})
const hostOk = computed(() => mail.host.trim().length > 0)
const fromOk = computed(() => mail.from_addr.trim().length > 0)

async function sendTest() {
  if (testing.value) return
  testing.value = true
  testOk.value = null
  testResult.value = ''
  try {
    const res = await cfg.testMail(mail)
    testOk.value = res.ok
    testResult.value = res.message || (res.ok ? '测试邮件已发送' : '测试邮件发送失败')
  } catch (e) {
    testOk.value = false
    const reason = e instanceof ApiError ? e.message : '发信通道暂不可用'
    testResult.value = `${reason}；安装完成后仍可在设置页验证。`
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <Mail class="mt-0.5 h-4 w-4 shrink-0" />
      <span>邮件通知为可选项。现在配置或点击左下角「跳过」均可；跳过之后仍可随时在「设置 → 邮件通知」中补充。</span>
    </div>

    <template v-if="!form.mail_skipped">
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">服务器地址 <span class="text-destructive">*</span></label>
          <Input v-model="mail.host" placeholder="发信服务器地址" :invalid="!hostOk && mail.host.length > 0" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">端口</label>
          <Input v-model="mail.port" type="number" placeholder="465" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">用户名</label>
          <Input v-model="mail.user" placeholder="登录发信服务的用户名" autocomplete="username" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">密码</label>
          <Input v-model="mail.password" type="password" placeholder="留空表示无需密码" autocomplete="new-password" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">发件地址 <span class="text-destructive">*</span></label>
          <Input v-model="mail.from_addr" placeholder="用于显示发件人的邮箱地址" :invalid="!fromOk && mail.from_addr.length > 0" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">发件人名称</label>
          <Input v-model="mail.from_name" placeholder="瞬旅 FlashTrip" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">超时（秒）</label>
          <Input v-model="mail.timeout_s" type="number" placeholder="10" />
        </div>
        <div class="flex items-end gap-3 pb-1">
          <label class="flex items-center gap-1.5 text-xs text-foreground">
            <input v-model="mail.use_ssl" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 使用 SSL 加密
          </label>
          <label class="flex items-center gap-1.5 text-xs text-foreground">
            <input v-model="mail.use_tls" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" /> 使用 STARTTLS
          </label>
        </div>
        <div class="space-y-1.5 sm:col-span-2">
          <label class="text-xs font-medium">默认收件人（每行一个，或用逗号分隔）</label>
          <textarea
            v-model="recipientsText"
            rows="2"
            class="flex w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm outline-none transition placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="用于收取出游提醒等通知的邮箱"
          />
          <p class="text-[11px] text-muted-foreground">SSL 与 STARTTLS 通常二选一；同时启用时优先使用 SSL。</p>
        </div>
      </div>

      <label class="flex items-center gap-2 text-xs text-foreground">
        <input v-model="mail.enabled" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" />
        安装完成后立即启用邮件通知
      </label>

      <div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button variant="outline" size="sm" :disabled="testing || !hostOk" @click="sendTest">
          <Loader2 v-if="testing" class="h-3.5 w-3.5 animate-spin" />
          <Send v-else class="h-3.5 w-3.5" /> 发送测试邮件
        </Button>
        <span v-if="testResult" class="text-xs" :class="testOk ? 'text-primary' : 'text-destructive'">{{ testResult }}</span>
        <span v-else class="text-[11px] text-muted-foreground">可用当前填写的内容试发一封测试邮件。</span>
      </div>

      <p v-if="!hostOk || !fromOk" class="text-xs text-destructive">
        带 * 的服务器地址与发件地址为必填项；填写完整后才能继续，或点击左下角「跳过」。
      </p>
      <p v-else class="text-xs text-muted-foreground">邮件配置已填写完整，可继续下一步。</p>
    </template>

    <div v-if="form.mail_skipped" class="rounded-lg border border-primary/30 bg-accent/50 p-3 text-xs leading-relaxed text-accent-foreground">
      已跳过邮件配置，可直接进入下一步。安装完成后可在设置页的「邮件通知」中随时启用。
    </div>
  </div>
</template>
