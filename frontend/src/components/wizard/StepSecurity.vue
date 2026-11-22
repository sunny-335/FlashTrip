<script setup lang="ts">
/** 第 5 步：主密钥强制备份、可选 Redis、AI 写工具开关。 */
import { computed, onMounted } from 'vue'
import { KeyRound, Download, Copy, CheckCircle2, Eye, EyeOff } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import { generateSecretKey, useConfigStore, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const cfg = useConfigStore()

onMounted(() => {
  if (!props.form.secret_key) props.form.secret_key = generateSecretKey()
})

const masked = computed(() =>
  props.probe.secretVisible
    ? props.form.secret_key
    : '•'.repeat(Math.min(props.form.secret_key.length, 48)),
)

/** 强制备份：Blob 下载成功后才解锁「下一步」。 */
function downloadBackup() {
  const key = props.form.secret_key
  const text = [
    '瞬旅 FlashTrip — 主密钥备份',
    '========================================',
    '',
    `secret_key: ${key}`,
    '',
    '说明：',
    '1. 该主密钥用于加密存储 AI / 地图 API Key，写入 /data/config.json。',
    '2. 请离线妥善保管；丢失后已加密数据无法解密，需重新配置密钥与全部密钥。',
    '3. 若部署时设置了环境变量 FLASHTRIP_SECRET_KEY，则以环境变量为准。',
    '',
    `生成时间：${new Date().toLocaleString('zh-CN')}`,
  ].join('\n')
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'flashtrip-secret-key.txt'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  props.probe.secretBackedUp = true
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(props.form.secret_key)
  } catch {
    /* 非安全上下文忽略，仍可手动下载 */
  }
}

async function testRedis() {
  props.probe.redis.error = ''
  props.probe.redis.tested = true
  try {
    const r = await cfg.testRedis(props.form.redis_url)
    props.probe.redis.ok = r.ok
    props.probe.redis.enabled = r.enabled
    props.form.redis_enabled = r.enabled
  } catch (e) {
    props.probe.redis.ok = false
    props.form.redis_enabled = false
    props.probe.redis.error = e instanceof ApiError ? e.message : (e as Error).message
  }
}

function toggleRedis() {
  props.probe.redis.skipped = !props.probe.redis.skipped
  if (props.probe.redis.skipped) {
    props.form.redis_enabled = false
    props.probe.redis.ok = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <KeyRound class="mt-0.5 h-4 w-4 shrink-0" />
      <span>主密钥加密所有第三方密钥，只在安装时生成一次、绝不进镜像与日志。该密钥将随安装请求提交，由后端写入配置并在安装响应中确认返回。</span>
    </div>

    <div class="rounded-lg border border-border bg-card p-3">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">主密钥 SECRET_KEY</span>
        <div class="flex items-center gap-1">
          <button class="rounded-md p-1.5 text-muted-foreground hover:bg-muted" title="显示/隐藏" @click="probe.secretVisible = !probe.secretVisible">
            <EyeOff v-if="probe.secretVisible" class="h-3.5 w-3.5" />
            <Eye v-else class="h-3.5 w-3.5" />
          </button>
          <button class="rounded-md p-1.5 text-muted-foreground hover:bg-muted" title="复制" @click="copyKey">
            <Copy class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <p class="mt-2 break-all rounded-md bg-muted px-3 py-2 font-mono text-xs text-foreground">{{ masked }}</p>
    </div>

    <div class="flex items-center gap-2">
      <Button size="sm" @click="downloadBackup"><Download class="h-3.5 w-3.5" /> 下载备份文件</Button>
      <span v-if="probe.secretBackedUp" class="inline-flex items-center gap-1 text-xs text-primary">
        <CheckCircle2 class="h-3.5 w-3.5" /> 已备份
      </span>
      <span v-else class="text-xs text-destructive">必须下载备份后才能继续</span>
    </div>

    <div class="border-t border-border pt-4">
      <label class="flex items-center gap-2 text-xs">
        <input :checked="!probe.redis.skipped" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" @change="toggleRedis" />
        启用外部 Redis（可选；不启用时使用进程内事件总线）
      </label>
      <div v-if="!probe.redis.skipped" class="mt-3 space-y-2">
        <div class="flex items-end gap-2">
          <div class="flex-1 space-y-1.5">
            <label class="text-xs font-medium">Redis 连接串</label>
            <Input v-model="form.redis_url" placeholder="redis://host:6379/0" />
          </div>
          <Button variant="outline" size="sm" @click="testRedis">测试</Button>
        </div>
        <p v-if="probe.redis.ok" class="text-xs text-primary">连接成功。</p>
        <p v-if="probe.redis.error" class="text-xs text-destructive">{{ probe.redis.error }}</p>
      </div>
    </div>

    <div class="border-t border-border pt-4">
      <label class="flex items-start gap-2 text-xs">
        <input v-model="form.ai_tools_enabled" type="checkbox" class="mt-0.5 h-3.5 w-3.5 accent-[var(--primary)]" />
        <span>启用 AI 写类工具（默认关闭）。开启后 Agent 的写操作仍需前端二次确认并经过同一套权限校验。</span>
      </label>
    </div>
  </div>
</template>
