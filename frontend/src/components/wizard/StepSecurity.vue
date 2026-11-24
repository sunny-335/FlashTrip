<script setup lang="ts">
/** 第 6 步：主密钥强制备份。Redis 已并入第 1 步（数据库），AI 写工具开关并入第 3 步（人工智能）。 */
import { computed, onMounted } from 'vue'
import { KeyRound, Download, Copy, CheckCircle2, Eye, EyeOff } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import { generateSecretKey, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()

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
    '1. 该主密钥用于加密存储人工智能与地图供应商密钥，写入服务端配置文件。',
    '2. 请离线妥善保管；丢失后已加密数据无法解密，需重新配置主密钥与全部供应商密钥。',
    '3. 若部署时设置了环境变量 FLASHTRIP_SECRET_KEY（服务端主密钥变量），则以环境变量为准。',
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
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <KeyRound class="mt-0.5 h-4 w-4 shrink-0" />
      <span>主密钥加密所有第三方密钥，只在安装时生成一次、绝不进镜像与日志。该密钥将随安装请求提交，由后端写入配置并在安装响应中确认返回。</span>
    </div>

    <div class="rounded-lg border border-border bg-card p-3">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">主密钥</span>
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
  </div>
</template>
