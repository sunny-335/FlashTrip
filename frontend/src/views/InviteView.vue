<script setup lang="ts">
/** 邀请落地页（standalone）：GET /invites/{token} 按 action 三分流。
 *  - login：已有密码的好友 → 跳 /login?next=/invite/<token>；已登录（从登录页返回）则直接接受邀请进行程；
 *  - reset：管理员勾选强制改密 → 「重置登录密码」表单；
 *  - setup：新用户首次加入 → 「设置登录密码」表单。
 *  reset / setup 均通过 accept 不带密码触发 3002，取 detail 里的 setupToken，
 *  再以 Bearer 凭据调 /auth/set-password，成功后服务端换发正式业务会话 Cookie。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { KeyRound, Loader2, TicketCheck, ShieldCheck } from 'lucide-vue-next'
import { api, request, ApiError } from '@/lib/api'
import { PERMISSION_LABELS } from '@/stores/collab'
import { useAuthStore } from '@/stores/auth'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'
import PasswordStrength from '@/components/settings/PasswordStrength.vue'

interface InviteInfo {
  channel: string
  target: string
  tripTitle: string
  permissionKeys: string[]
  expiresAt: string
  maxUses: number
  usedCount: number
  requiresPassword: boolean
  forceReset: boolean
  hasPassword: boolean
  nickname: string | null
  email: string | null
  action: 'login' | 'reset' | 'setup'
  next: string
}
interface AcceptResult {
  action?: string
  tripId?: string
  next?: string
  scope?: string
}
interface SetupDetail {
  scope: 'setup' | 'reset'
  setupToken: string
  userId: string
  tripId: string
  invitationId: string
  action: string
}
/** PasswordStrength 通过 change 回传的强度指标，本页只用到校验结论与提示。 */
interface StrengthInfo { valid: boolean; meetsPolicy: boolean; hints: string[]; label: string }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const token = computed(() => String(route.params.token ?? ''))

const info = ref<InviteInfo | null>(null)
const displayName = ref('')
const password = ref('')
const confirm = ref('')
const strength = ref<StrengthInfo | null>(null)
const loading = ref(true)
const redirecting = ref(false)
const submitting = ref(false)
const error = ref('')
const loadError = ref('')

const channelLabel: Record<string, string> = { phone: '手机号', email: '邮箱', username: '用户名' }
/** reset / setup 的表单标题与按钮文案。 */
const formTitle = computed(() => (info.value?.action === 'reset' ? '重置登录密码' : '设置登录密码'))
const isReset = computed(() => info.value?.action === 'reset')

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败，请重试'
}

function parseSetupDetail(raw: string | undefined): SetupDetail | null {
  if (!raw) return null
  try {
    const d = JSON.parse(raw) as SetupDetail
    return d?.setupToken ? d : null
  } catch {
    return null
  }
}

async function goTrip(tripId: string) {
  await router.replace(tripId ? `/trips/${tripId}/plan` : '/dashboard')
}

/** 跳登录页并把当前邀请链接作为登录成功后要返回的地址。 */
async function goLogin() {
  redirecting.value = true
  await router.replace(`/login?next=${encodeURIComponent(`/invite/${token.value}`)}`)
}

/** 已有密码的好友：未登录跳登录页；已登录（登录页带着 next 回来）则直接接受并入行程，避免反复跳登录。 */
async function handleLoginAction() {
  const me = await auth.me()
  if (!me) { await goLogin(); return }
  try {
    const ok = await api.post<AcceptResult>(`/invites/${encodeURIComponent(token.value)}/accept`, {})
    await goTrip(ok.tripId || '')
  } catch (e) {
    error.value = messageOf(e)
  }
}

onMounted(async () => {
  try {
    const data = await api.get<InviteInfo>(`/invites/${encodeURIComponent(token.value)}`)
    info.value = data
    displayName.value = data.nickname || ''
    if (data.action === 'login') await handleLoginAction()
  } catch (e) {
    loadError.value = messageOf(e)
  } finally {
    loading.value = false
  }
})

/** 不带密码调用 accept，后端抛 3002 并在 detail 里给出一次性 setupToken。 */
async function requestSetupToken(): Promise<SetupDetail> {
  try {
    const ok = await api.post<AcceptResult>(`/invites/${encodeURIComponent(token.value)}/accept`, {
      display_name: displayName.value.trim() || undefined,
    })
    // 少数情况下后端直接完成（例如已被接受），按其返回的行程 ID 处理
    if (ok?.tripId) return { scope: 'setup', setupToken: '', userId: '', tripId: ok.tripId, invitationId: '', action: 'full' }
    throw new Error('邀请未进入设密流程，请重新打开链接')
  } catch (e) {
    if (e instanceof ApiError && e.code === 3002) {
      const detail = parseSetupDetail(e.detail)
      if (detail) return detail
      throw new Error('邀请已接受，但未取得设密凭据，请使用邀请链接重试')
    }
    throw e
  }
}

async function submit() {
  if (submitting.value) return
  if (password.value.length < 8 || password.value.length > 32) {
    error.value = '密码长度需为 8–32 位'
    return
  }
  if (password.value !== confirm.value) { error.value = '两次输入的密码不一致'; return }
  if (strength.value && !strength.value.valid) {
    error.value = '密码强度未达到要求：' + (strength.value.hints?.join('；') || '请增加字符种类并避免连续或重复字符')
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const setup = await requestSetupToken()
    // 后端已直接完成的情况无需再设密
    if (!setup.setupToken) { await goTrip(setup.tripId); return }
    const res = await request<{ tripId: string; scope: string }>('/auth/set-password', {
      method: 'POST',
      headers: { Authorization: `Bearer ${setup.setupToken}` },
      body: JSON.stringify({ new_password: password.value }),
    })
    await goTrip(res.tripId || setup.tripId)
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
    <div class="w-full max-w-md">
      <div class="mb-6 flex items-center gap-2.5">
        <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">瞬</span>
        <div>
          <h1 class="text-base font-semibold leading-tight">加入行程</h1>
          <p class="text-xs text-muted-foreground">瞬旅 FlashTrip · 协作邀请</p>
        </div>
      </div>

      <div class="rounded-lg border border-border bg-card p-6 shadow-sm">
        <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">
          <Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在校验邀请…
        </div>

        <div v-else-if="loadError" class="space-y-3 text-center">
          <p class="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {{ loadError }}
          </p>
          <p class="text-xs text-muted-foreground">链接可能已过期、被撤销或使用次数已用尽。</p>
          <Button variant="outline" size="sm" @click="router.replace('/login')">前往登录</Button>
        </div>

        <!-- login 分支：正在跳转登录页 -->
        <div v-else-if="info && info.action === 'login'" class="space-y-3 py-4 text-center">
          <Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin text-primary" />
          <p class="text-sm text-foreground">{{ redirecting ? '正在前往登录页…' : '正在加入行程…' }}</p>
          <p class="text-xs text-muted-foreground">该账号已设置过密码，登录后即可查看行程。</p>
          <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ error }}</p>
          <Button variant="outline" size="sm" @click="goLogin">前往登录</Button>
        </div>

        <!-- reset / setup 分支：设密表单 -->
        <template v-else-if="info">
          <div class="mb-4 rounded-lg border border-border bg-muted/40 p-3">
            <div class="flex items-center gap-2">
              <TicketCheck class="h-4 w-4 text-primary" />
              <span class="text-sm font-semibold">{{ info.tripTitle || '未命名行程' }}</span>
            </div>
            <p class="mt-1.5 text-xs text-muted-foreground">
              通过{{ channelLabel[info.channel] ?? info.channel }}邀请 <span class="font-medium text-foreground">{{ info.target }}</span>
            </p>
            <div class="mt-2 flex flex-wrap gap-1">
              <Badge v-for="k in info.permissionKeys" :key="k" variant="outline">
                {{ PERMISSION_LABELS[k] ?? k }}
              </Badge>
            </div>
            <p class="mt-2 text-[11px] text-muted-foreground">
              剩余 {{ Math.max(0, info.maxUses - info.usedCount) }} / {{ info.maxUses }} 次 · 有效期至 {{ info.expiresAt || '—' }}
            </p>
          </div>

          <div class="mb-4 flex items-start gap-2 rounded-lg border border-primary/30 bg-accent/40 p-3 text-xs leading-relaxed text-muted-foreground">
            <ShieldCheck class="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <span v-if="isReset">管理员要求你重置登录密码，设置新密码后才能进入行程。请牢记新密码，之后可在登录页直接使用。</span>
            <span v-else>首次加入需设置登录密码，完成后才会发放业务访问令牌。请牢记密码，之后可在登录页直接使用。</span>
          </div>

          <h2 class="mb-3 text-sm font-semibold text-foreground">{{ formTitle }}</h2>
          <form class="space-y-3" @submit.prevent="submit">
            <div class="space-y-1.5">
              <label class="text-xs font-medium">显示名称（可选）</label>
              <Input v-model="displayName" placeholder="例如：小明" autocomplete="name" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium">{{ isReset ? '新密码' : '设置登录密码' }}</label>
              <Input v-model="password" type="password" placeholder="8–32 位" autocomplete="new-password" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium">确认密码</label>
              <Input v-model="confirm" type="password" placeholder="再次输入" autocomplete="new-password" />
            </div>

            <!-- 密码强度：复用设置页组件，统一 8–32 位与字符类别规则提示 -->
            <PasswordStrength :password="password" @change="(s) => strength = s" />
            <p class="text-[11px] leading-relaxed text-muted-foreground">
              密码长度 8–32 位，建议包含大小写字母、数字与特殊字符，避免连续或重复字符。
            </p>

            <Button type="submit" class="w-full" :disabled="submitting">
              <Loader2 v-if="submitting" class="h-3.5 w-3.5 animate-spin" />
              <KeyRound v-else class="h-3.5 w-3.5" />
              {{ submitting ? '正在加入…' : (isReset ? '重置密码并进入行程' : '设置密码并进入行程') }}
            </Button>
          </form>

          <p v-if="error" class="mt-3 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
            {{ error }}
          </p>
        </template>
      </div>
      <p class="mt-4 text-center text-[11px] text-muted-foreground">邀请链接中的明文令牌仅用于本页校验，服务端只保存其哈希值。</p>
    </div>
  </div>
</template>
