<script setup lang="ts">
/**
 * 账户与安全分区：危险项解锁、主密钥轮换备份、修改登录密码。
 * 说明：PUT /settings 已移除解锁门禁，常规设置登录后即可保存；
 * 本页解锁仅用于主密钥轮换等危险操作（后端仍要求解锁）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  LockKeyhole, UnlockKeyhole, KeyRound, ShieldCheck, RefreshCw,
  Loader2, Copy, Check, Download,
} from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'
import PasswordStrength from './PasswordStrength.vue'

const unlocked = ref(false)
const unlockForm = reactive({ username: '', password: '' })
const unlocking = ref(false)
const unlockError = ref('')

const rotating = ref(false)
const newSecret = ref('')
const copiedSecret = ref(false)

const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })
const strengthOk = ref(false)
const changingPwd = ref(false)

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
  try {
    const s = await api.get<{ unlocked?: boolean }>('/wizard/status')
    unlocked.value = Boolean(s.unlocked)
  } catch {
    // 状态读取失败不阻断表单，保存类错误由具体动作显示
    unlocked.value = false
  }
}

async function unlock() {
  if (!unlockForm.username.trim() || !unlockForm.password || unlocking.value) return
  unlocking.value = true
  unlockError.value = ''
  try {
    await api.post('/wizard/unlock', {
      username: unlockForm.username.trim(),
      password: unlockForm.password,
    })
    unlocked.value = true
    unlockForm.password = ''
    flash('已解锁，现在可以轮换主密钥')
  } catch (e) {
    unlockError.value = messageOf(e)
  } finally {
    unlocking.value = false
  }
}

async function rotateSecret() {
  if (rotating.value) return
  rotating.value = true
  error.value = ''
  newSecret.value = ''
  try {
    const res = await api.post<{ rotated: boolean; need_backup_secret: boolean; secret_key: string }>(
      '/settings/secret/rotate',
    )
    newSecret.value = res.secret_key || ''
    flash('主密钥已轮换，请立即下载备份')
  } catch (e) {
    // 由环境变量提供主密钥时后端会明确拒绝，原样展示中文原因
    error.value = messageOf(e)
  } finally {
    rotating.value = false
  }
}

function downloadSecret() {
  if (!newSecret.value) return
  const text = `瞬旅 FlashTrip 主密钥备份\n\nsecret_key: ${newSecret.value}\n\n请离线妥善保管，丢失后已加密的第三方密钥将无法解密。\n`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'flashtrip-secret-key.txt'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function copySecret() {
  if (!newSecret.value) return
  try {
    await navigator.clipboard.writeText(newSecret.value)
    copiedSecret.value = true
    window.setTimeout(() => { copiedSecret.value = false }, 1800)
  } catch {
    // 非安全上下文忽略，用户仍可手动复制或下载
  }
}

function onStrength(info: { meetsPolicy: boolean }) {
  strengthOk.value = info.meetsPolicy
}
const confirmOk = computed(() => pwdForm.new_password === pwdForm.confirm)
const canChangePwd = computed(() => Boolean(
  pwdForm.old_password && pwdForm.new_password && confirmOk.value && strengthOk.value,
))

async function changePassword() {
  if (!canChangePwd.value || changingPwd.value) return
  changingPwd.value = true
  error.value = ''
  try {
    await api.post('/auth/change-password', {
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password,
    })
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm = ''
    flash('登录密码已修改')
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    changingPwd.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ error }}</p>
    <p v-if="notice" class="rounded-md border border-primary/40 bg-accent px-2.5 py-2 text-xs text-accent-foreground">{{ notice }}</p>

    <!-- 危险项解锁 -->
    <Card class="space-y-3">
      <div class="flex items-center justify-between gap-2">
        <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
          <LockKeyhole class="h-4 w-4 text-primary" /> 配置解锁
        </h2>
        <Badge :variant="unlocked ? 'default' : 'secondary'">{{ unlocked ? '已解锁' : '已锁定' }}</Badge>
      </div>
      <p class="text-xs leading-relaxed text-muted-foreground">
        解锁仅用于主密钥轮换等危险操作，会写入审计记录；人工智能、地图、邮件、天气、备份与偏好等常规设置登录后即可保存，无需解锁。
      </p>
      <form v-if="!unlocked" class="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" @submit.prevent="unlock">
        <Input v-model="unlockForm.username" placeholder="管理员用户名" autocomplete="username" />
        <Input v-model="unlockForm.password" type="password" placeholder="管理员密码" autocomplete="current-password" />
        <Button type="submit" size="sm" :disabled="unlocking || !unlockForm.username || !unlockForm.password">
          <Loader2 v-if="unlocking" class="h-3.5 w-3.5 animate-spin" />
          <UnlockKeyhole v-else class="h-3.5 w-3.5" /> 解锁
        </Button>
      </form>
      <p v-if="unlockError" class="text-xs text-destructive">{{ unlockError }}</p>
    </Card>

    <!-- 主密钥 -->
    <Card class="space-y-3">
      <div class="flex items-center justify-between gap-2">
        <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
          <KeyRound class="h-4 w-4 text-primary" /> 主密钥
        </h2>
        <Button variant="outline" size="sm" :disabled="rotating || !unlocked" @click="rotateSecret">
          <Loader2 v-if="rotating" class="h-3.5 w-3.5 animate-spin" />
          <RefreshCw v-else class="h-3.5 w-3.5" /> 轮换
        </Button>
      </div>
      <div class="rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
        <p class="flex items-center gap-1.5 font-medium text-foreground"><ShieldCheck class="h-3.5 w-3.5" /> 请务必保留备份</p>
        <p class="mt-1.5">
          主密钥用于加密所有第三方密钥。一旦丢失且无备份，已加密的密钥将无法解密，需要重新填写；数据库中的行程数据本身不受影响。
          轮换后请立即下载备份并离线妥善保存。若主密钥由环境变量
          <code class="font-mono">FLASHTRIP_SECRET_KEY</code>（服务端主密钥变量）提供，请直接更换该变量并重启。
        </p>
      </div>
      <p v-if="!unlocked" class="text-[11px] text-muted-foreground">轮换主密钥需先在上方解锁。</p>

      <div v-if="newSecret" class="space-y-2">
        <p class="text-xs font-medium text-foreground">新主密钥（仅本次展示）</p>
        <Input :model-value="newSecret" readonly class="font-mono text-[11px]" />
        <div class="flex gap-2">
          <Button size="sm" @click="downloadSecret"><Download class="h-3.5 w-3.5" /> 下载备份</Button>
          <Button variant="outline" size="sm" @click="copySecret">
            <Check v-if="copiedSecret" class="h-3.5 w-3.5" /><Copy v-else class="h-3.5 w-3.5" />
            {{ copiedSecret ? '已复制' : '复制' }}
          </Button>
        </div>
      </div>
    </Card>

    <!-- 修改密码 -->
    <Card class="space-y-3">
      <div>
        <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
          <ShieldCheck class="h-4 w-4 text-primary" /> 修改登录密码
        </h2>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
          新密码需为 8–32 位、至少包含两类字符，且不含连续或重复字符串。
        </p>
      </div>
      <div class="grid gap-2 sm:grid-cols-2">
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-foreground">当前密码</label>
          <Input v-model="pwdForm.old_password" type="password" placeholder="当前登录密码" autocomplete="current-password" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-foreground">确认新密码</label>
          <Input
            v-model="pwdForm.confirm"
            type="password"
            placeholder="再次输入新密码"
            autocomplete="new-password"
            :invalid="pwdForm.confirm.length > 0 && !confirmOk"
          />
        </div>
        <div class="space-y-1.5 sm:col-span-2">
          <label class="text-xs font-medium text-foreground">新密码</label>
          <Input v-model="pwdForm.new_password" type="password" placeholder="输入新密码" autocomplete="new-password" />
        </div>
      </div>
      <PasswordStrength :password="pwdForm.new_password" @change="onStrength" />
      <p v-if="pwdForm.confirm.length > 0 && !confirmOk" class="text-xs text-destructive">两次输入的新密码不一致。</p>
      <div class="flex items-center gap-2">
        <Button size="sm" :disabled="!canChangePwd || changingPwd" @click="changePassword">
          <Loader2 v-if="changingPwd" class="h-3.5 w-3.5 animate-spin" />
          确认修改
        </Button>
        <span v-if="!strengthOk && pwdForm.new_password" class="text-[11px] text-muted-foreground">新密码未达到强度要求。</span>
      </div>
    </Card>
  </div>
</template>
