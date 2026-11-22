<script setup lang="ts">
/**
 * 登录页（standalone）：成功后按 ?next 跳转；
 * 邀请成员 must_set_password=true 时在本页切换为「首次设置密码」流程
 * （调用 /auth/set-password，完成后换发正式业务令牌）。
 * 密码强度组件仅用于首次设密场景，登录表单保持原逻辑。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { KeyRound, Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import PasswordStrength from '@/components/settings/PasswordStrength.vue'
import { useAuthStore } from '@/stores/auth'

interface StrengthInfo { valid: boolean; hints: string[] }

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const mode = ref<'login' | 'password'>('login')
const username = ref('')
const password = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const strength = ref<StrengthInfo | null>(null)
const error = ref('')
const loading = ref(false)

const title = computed(() => (mode.value === 'login' ? '登录瞬旅' : '设置密码'))
const subtitle = computed(() =>
  mode.value === 'login' ? '使用安装时创建的管理员账号登录' : '你是受邀成员，请先设置密码以激活账号',
)

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败，请重试'
}

function goNext() {
  const q = route.query.next
  const target = typeof q === 'string' && q.startsWith('/') && !q.startsWith('//') ? q : '/dashboard'
  void router.replace(target)
}

async function onLogin() {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const u = await auth.login(username.value.trim(), password.value)
    if (u.must_set_password) {
      mode.value = 'password'
      return
    }
    goNext()
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
}

async function onSetPassword() {
  if (newPassword.value.length < 8 || newPassword.value.length > 32) {
    error.value = '密码长度需为 8–32 位'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  if (strength.value && !strength.value.valid) {
    error.value = '密码强度未达到要求：' + (strength.value.hints?.join('；') || '请增加字符种类并避免连续或重复字符')
    return
  }
  loading.value = true
  error.value = ''
  try {
    await auth.setPassword(newPassword.value)
    goNext()
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
    <div class="w-full max-w-sm">
      <div class="mb-6 flex items-center gap-2.5">
        <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">瞬</span>
        <div>
          <h1 class="text-base font-semibold leading-tight">瞬旅 FlashTrip</h1>
          <p class="text-xs text-muted-foreground">{{ subtitle }}</p>
        </div>
      </div>

      <div class="rounded-lg border border-border bg-card p-6 shadow-sm">
        <div class="mb-4 flex items-center gap-2">
          <KeyRound class="h-4 w-4 text-primary" />
          <h2 class="text-sm font-semibold">{{ title }}</h2>
        </div>

        <form v-if="mode === 'login'" class="space-y-3" @submit.prevent="onLogin">
          <div class="space-y-1.5">
            <label class="text-xs font-medium">用户名</label>
            <Input v-model="username" placeholder="请输入用户名" autocomplete="username" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium">密码</label>
            <Input v-model="password" type="password" placeholder="请输入密码" autocomplete="current-password" />
          </div>
          <Button type="submit" class="w-full" :disabled="loading">
            <Loader2 v-if="loading" class="h-3.5 w-3.5 animate-spin" />
            {{ loading ? '登录中…' : '登录' }}
          </Button>
        </form>

        <!-- 首次设密：集成密码强度组件，统一 8–32 位规则提示 -->
        <form v-else class="space-y-3" @submit.prevent="onSetPassword">
          <div class="rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
            受邀账号需设置密码后才能获得业务访问令牌。密码长度 8–32 位，经安全算法哈希后存储。
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium">新密码</label>
            <Input v-model="newPassword" type="password" placeholder="8–32 位" autocomplete="new-password" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium">确认新密码</label>
            <Input v-model="confirmPassword" type="password" placeholder="再次输入" autocomplete="new-password" />
          </div>
          <PasswordStrength :password="newPassword" @change="(s) => strength = s" />
          <p class="text-[11px] leading-relaxed text-muted-foreground">
            建议包含大小写字母、数字与特殊字符，避免连续或重复字符。
          </p>
          <Button type="submit" class="w-full" :disabled="loading">
            <Loader2 v-if="loading" class="h-3.5 w-3.5 animate-spin" />
            {{ loading ? '设置中…' : '设置密码并进入' }}
          </Button>
        </form>

        <div v-if="error" class="mt-3 rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">
          {{ error }}
        </div>
      </div>
      <p class="mt-4 text-center text-[11px] text-muted-foreground">登录状态由浏览器安全会话保存，退出请点顶部导航的退出按钮。</p>
    </div>
  </div>
</template>
