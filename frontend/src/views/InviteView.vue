<script setup lang="ts">
/** 邀请落地页（standalone）：GET /invites/{token} → 接受 → 首次设置登录密码 → 进入行程。
 *
 *  后端 accept 未带 password 时创建 must_set_password 用户并返回 3002，
 *  detail 是 JSON 字符串 {userId, tripId, setupToken}；前端凭该 setup 作用域 token
 *  通过 Authorization: Bearer 调 /auth/set-password，成功后服务端换发正式业务 cookie。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { KeyRound, Loader2, TicketCheck, ShieldCheck } from 'lucide-vue-next'
import { api, request, ApiError } from '@/lib/api'
import { PERMISSION_LABELS } from '@/stores/collab'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'

interface InviteInfo {
  channel: string
  target: string
  tripTitle: string
  permissionKeys: string[]
  expiresAt: string
  maxUses: number
  usedCount: number
  requiresPassword: boolean
}
interface AcceptResult { accessToken: string; userId: string; tripId: string }
interface SetupDetail { userId: string; tripId: string; setupToken: string }

const route = useRoute()
const router = useRouter()
const token = computed(() => String(route.params.token ?? ''))

const info = ref<InviteInfo | null>(null)
const displayName = ref('')
const password = ref('')
const confirm = ref('')
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const loadError = ref('')

const channelLabel: Record<string, string> = { phone: '手机号', email: '邮箱', username: '用户名' }

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

onMounted(async () => {
  try {
    info.value = await api.get<InviteInfo>(`/invites/${encodeURIComponent(token.value)}`)
  } catch (e) {
    loadError.value = messageOf(e)
  } finally {
    loading.value = false
  }
})

async function goTrip(tripId: string) {
  await router.replace(tripId ? `/trips/${tripId}/plan` : '/dashboard')
}

async function submit() {
  if (submitting.value) return
  if (password.value.length < 8) { error.value = '密码至少需要 8 位'; return }
  if (password.value !== confirm.value) { error.value = '两次输入的密码不一致'; return }
  submitting.value = true
  error.value = ''
  try {
    // ① 接受邀请（不传 password，触发首次设密流程）
    const payload = { display_name: displayName.value.trim() || undefined }
    try {
      const ok = await api.post<AcceptResult>(`/invites/${encodeURIComponent(token.value)}/accept`, payload)
      // 已设密的老用户：后端直接换发业务 cookie，直接进入行程
      await goTrip(ok.tripId)
      return
    } catch (e) {
      if (!(e instanceof ApiError) || e.code !== 3002) throw e
      // ② 3002：从 detail 取 setupToken，用 Bearer 调用 /auth/set-password
      const setup = parseSetupDetail(e.detail)
      if (!setup) throw new Error('邀请已接受，但未取得设密凭证，请使用邀请链接重新登录')
      await request('/auth/set-password', {
        method: 'POST',
        headers: { Authorization: `Bearer ${setup.setupToken}` },
        body: JSON.stringify({ new_password: password.value }),
      })
      // ③ set-password 响应已 set-cookie（正式业务 token）
      await goTrip(setup.tripId)
    }
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
            <span>首次加入需设置登录密码，完成后才会发放业务访问令牌。请牢记密码，之后可在登录页直接使用。</span>
          </div>

          <form class="space-y-3" @submit.prevent="submit">
            <div class="space-y-1.5">
              <label class="text-xs font-medium">显示名称（可选）</label>
              <Input v-model="displayName" placeholder="例如：小明" autocomplete="name" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium">设置登录密码</label>
              <Input v-model="password" type="password" placeholder="至少 8 位" autocomplete="new-password" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium">确认密码</label>
              <Input v-model="confirm" type="password" placeholder="再次输入" autocomplete="new-password" />
            </div>
            <Button type="submit" class="w-full" :disabled="submitting">
              <Loader2 v-if="submitting" class="h-3.5 w-3.5 animate-spin" />
              <KeyRound v-else class="h-3.5 w-3.5" />
              {{ submitting ? '正在加入…' : '接受邀请并设置密码' }}
            </Button>
          </form>

          <p v-if="error" class="mt-3 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
            {{ error }}
          </p>
        </template>
      </div>
      <p class="mt-4 text-center text-[11px] text-muted-foreground">邀请链接中的明文令牌仅用于本页校验，服务端只保存其哈希。</p>
    </div>
  </div>
</template>
