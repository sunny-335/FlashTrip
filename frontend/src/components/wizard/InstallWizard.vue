<script setup lang="ts">
/**
 * 七步安装向导编排：数据库 → 管理员 → 人工智能 → 地图 → 邮件通知（可跳过）→ 安全 → 确认。
 * 逐步调 test-db / test-ai / test-map / test-redis / test-mail（在对应 Step 内），
 * 失败显示具体错误、允许回退修改；最终由 buildPayload 装配后 POST /wizard/install。
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Check, ChevronLeft, ChevronRight, Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import { clearStatusCache } from '@/router'
import Button from '@/components/ui/Button.vue'
import {
  buildPayload, createInstallForm, createWizardProbe, generateSecretKey, MAP_PRESETS,
  useConfigStore, type InstallIn,
} from '@/stores/config'
import StepDb from './StepDb.vue'
import StepAdmin from './StepAdmin.vue'
import StepAi from './StepAi.vue'
import StepMap from './StepMap.vue'
import StepMail from './StepMail.vue'
import StepSecurity from './StepSecurity.vue'
import StepConfirm from './StepConfirm.vue'

const cfg = useConfigStore()
const router = useRouter()

// 步骤条用短名，避免七个标签在窄宽度下互相挤压成「人工…」；
// title 是完整步骤名，用于步骤条悬浮提示与页面标题。
const steps = [
  { key: 'database', label: '数据库', title: '数据库' },
  { key: 'admin', label: '管理员', title: '管理员' },
  { key: 'ai', label: 'AI', title: '人工智能' },
  { key: 'map', label: '地图', title: '地图' },
  { key: 'mail', label: '邮件', title: '邮件通知', skippable: true },
  { key: 'security', label: '安全', title: '安全备份' },
  { key: 'confirm', label: '确认', title: '确认安装' },
]
const components = [StepDb, StepAdmin, StepAi, StepMap, StepMail, StepSecurity, StepConfirm]
/** 当前步是否可跳过（仅邮件通知一步可跳过）。 */
const currentSkippable = computed(() => Boolean(steps[step.value]?.skippable))

const form = reactive<InstallIn>(createInstallForm())
// 确保进入安全步之前也有值（StepSecurity 亦会兜底生成）
if (!form.secret_key) form.secret_key = generateSecretKey()
const probe = reactive(createWizardProbe())

const step = ref(0)
const installing = ref(false)
const installError = ref('')
const installed = ref(false)

const currentComponent = computed(() => components[step.value])

const adminValid = computed(
  () => form.admin.username.trim().length > 0
    && form.admin.password.length >= 8
    && form.admin.password === probe.adminConfirm
    && probe.adminMeetsPolicy,
)
const aiValid = computed(
  () => probe.ai.skipped
    || (Boolean(form.ai_providers[0]?.base_url.trim()) && Boolean(form.ai_providers[0]?.model.trim())),
)
/** 邮件为可跳过步骤：已跳过即放行，否则要求服务器地址与发件地址完整。 */
const mailValid = computed(
  () => form.mail_skipped
    || (Boolean(form.mail?.host?.trim()) && Boolean(form.mail?.from_addr?.trim())),
)
const mapProvider = computed(() => form.map_providers.find((p) => p.id === form.map_default_provider_id))
const mapNeedsKey = computed(() => MAP_PRESETS.find((p) => p.id === form.map_default_provider_id)?.needsKey ?? false)
const mapKeyValid = computed(() => !mapNeedsKey.value || Boolean(mapProvider.value?.key.trim()))

/** 每步可继续条件：连通性允许跳过，但供应商必需密钥仍须填写。 */
const canNext = computed(() => {
  switch (step.value) {
    case 0: return probe.db.ok && (!form.redis_host.trim() || probe.redis.ok)
    case 1: return adminValid.value
    case 2: return aiValid.value
    case 3: return mapKeyValid.value && (probe.map.ok || probe.map.skipped)
    case 4: return mailValid.value
    case 5: return probe.secretBackedUp
    default: return true
  }
})

function goStep(n: number) {
  installError.value = ''
  step.value = Math.max(0, Math.min(steps.length - 1, n))
}

function next() {
  if (canNext.value && step.value < steps.length - 1) goStep(step.value + 1)
}

/** 跳过当前可跳过步骤：邮件配置置为跳过标记后前进。 */
function skip() {
  if (!currentSkippable.value) return
  if (steps[step.value].key === 'mail') form.mail_skipped = true
  if (step.value < steps.length - 1) goStep(step.value + 1)
}

/** 后端 install 响应若返回（或与本地不同的）主密钥，以其为准补一次下载兜底。 */
function backupIfNeeded(secret?: string) {
  if (!secret || secret === form.secret_key) return
  const blob = new Blob([`瞬旅 FlashTrip 主密钥（后端返回）\n\nsecret_key: ${secret}\n`], {
    type: 'text/plain;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'flashtrip-secret-key.txt'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function submit() {
  // 提交前复核硬性前置条件，未满足则跳回对应步骤，绝不静默跳过
  if (!probe.db.ok) {
    goStep(0)
    installError.value = '数据库连接测试尚未通过，请返回第 1 步处理。'
    return
  }
  if (!adminValid.value) {
    goStep(1)
    installError.value = '管理员账号信息或密码强度不达标，请返回第 2 步处理。'
    return
  }
  if (!mapKeyValid.value) {
    goStep(3)
    installError.value = `${MAP_PRESETS.find((p) => p.id === form.map_default_provider_id)?.label ?? '所选地图供应商'}需要配置密钥，连通性探测可以跳过，但密钥不能省略。`
    return
  }
  if (!mailValid.value) {
    goStep(4)
    installError.value = '邮件配置未填写完整，请返回第 5 步补充或点击「跳过」。'
    return
  }
  if (!probe.secretBackedUp) {
    goStep(5)
    installError.value = '主密钥尚未下载备份，请返回第 6 步处理。'
    return
  }
  installing.value = true
  installError.value = ''
  try {
    const res = await cfg.install(buildPayload(form, probe))
    if (res.need_backup_secret && res.secret_key) backupIfNeeded(res.secret_key)
    installed.value = true
    clearStatusCache()
    await router.push('/login')
  } catch (e) {
    installError.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    installing.value = false
  }
}
</script>

<template>
  <div class="w-full">
    <!-- 步骤条：紧凑圆点 + 短标签，不换行堆叠 -->
    <ol class="mb-5 flex items-center gap-1.5">
      <li v-for="(s, i) in steps" :key="s.key" class="flex min-w-0 flex-1 items-center gap-1.5">
        <div class="flex min-w-0 items-center gap-1.5">
          <span
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium"
            :class="i < step
              ? 'border-primary bg-primary text-primary-foreground'
              : i === step
                ? 'border-primary text-primary'
                : 'border-border text-muted-foreground'"
          >
            <Check v-if="i < step" class="h-3 w-3" />
            <span v-else>{{ i + 1 }}</span>
          </span>
          <span
            class="truncate text-xs"
            :class="i === step ? 'font-medium text-foreground' : 'text-muted-foreground'"
            :title="s.title"
          >
            {{ s.label }}
          </span>
        </div>
        <div v-if="i < steps.length - 1" class="h-px min-w-2 flex-1 bg-border" />
      </li>
    </ol>

    <div class="mb-2">
      <h2 class="text-base font-semibold text-foreground">{{ steps[step].title }}</h2>
      <p class="mt-0.5 text-xs text-muted-foreground">第 {{ step + 1 }} / {{ steps.length }} 步</p>
    </div>

    <div class="min-h-[320px]">
      <component :is="currentComponent" :form="form" :probe="probe" @edit="goStep" />
    </div>

    <div v-if="installError" class="mt-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ installError }}
    </div>
    <div v-if="installed" class="mt-4 rounded-lg border border-primary/40 bg-primary/5 p-3 text-xs text-primary">
      安装完成，正在跳转到登录页…
    </div>

    <div class="mt-6 flex items-center justify-between gap-2 border-t border-border pt-4">
      <Button v-if="step > 0" variant="ghost" size="sm" :disabled="installing" @click="goStep(step - 1)">
        <ChevronLeft class="h-3.5 w-3.5" /> 上一步
      </Button>
      <span v-else />
      <div class="flex items-center gap-2">
        <Button v-if="currentSkippable" variant="ghost" size="sm" :disabled="installing" @click="skip">
          跳过
        </Button>
        <Button v-if="step < steps.length - 1" size="sm" :disabled="!canNext" @click="next">
          下一步 <ChevronRight class="h-3.5 w-3.5" />
        </Button>
        <Button v-else size="sm" :disabled="installing" @click="submit">
          <Loader2 v-if="installing" class="h-3.5 w-3.5 animate-spin" />
          {{ installing ? '安装中…' : '完成安装' }}
        </Button>
      </div>
    </div>
  </div>
</template>
