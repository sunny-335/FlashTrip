<script setup lang="ts">
/** 创建邀请：渠道 + 目标 + 权限 + TTL + 次数；成功后展示一次性明文链接（DB 只存 hash）。 */
import { computed, ref, watch } from 'vue'
import { Link2, Copy, Check, Loader2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { DEFAULT_PERMISSION_KEYS, PERMISSION_KEYS, type CreateInviteResult } from '@/stores/collab'
import Dialog from '@/components/ui/Dialog.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import PermissionMatrix from './PermissionMatrix.vue'

const props = defineProps<{ tripId: string }>()
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ created: [] }>()

const channel = ref<'phone' | 'email' | 'username'>('username')
const target = ref('')
const permissions = ref<Record<string, boolean>>({
  ...Object.fromEntries(PERMISSION_KEYS.map((k) => [k, DEFAULT_PERMISSION_KEYS.includes(k)])),
})
const expiresDays = ref(7)
const maxUses = ref(1)
const busy = ref(false)
const error = ref('')
const result = ref<CreateInviteResult | null>(null)
const copied = ref(false)

const channelOptions = [
  { value: 'username', label: '用户名' },
  { value: 'email', label: '邮箱' },
  { value: 'phone', label: '手机号' },
]
const placeholders: Record<string, string> = {
  username: '对方的用户名',
  email: 'name@example.com',
  phone: '13800000000',
}

const inviteLink = computed(() => {
  if (!result.value) return ''
  const url = result.value.inviteUrl || `/invite/${result.value.token}`
  return `${window.location.origin}${url.startsWith('/') ? url : `/${url}`}`
})

watch(open, (v) => {
  if (v) {
    // 每次打开重置表单，避免上一轮的明文链接残留
    target.value = ''
    channel.value = 'username'
    expiresDays.value = 7
    maxUses.value = 1
    permissions.value = Object.fromEntries(PERMISSION_KEYS.map((k) => [k, DEFAULT_PERMISSION_KEYS.includes(k)]))
    error.value = ''
    result.value = null
    copied.value = false
  }
})

async function submit() {
  if (!target.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const keys = PERMISSION_KEYS.filter((k) => permissions.value[k])
    result.value = await api.post<CreateInviteResult>(`/trips/${props.tripId}/invites`, {
      channel: channel.value,
      target_value: target.value.trim(),
      permission_keys: keys.length ? keys : [...DEFAULT_PERMISSION_KEYS],
      expires_days: Number(expiresDays.value) || 7,
      max_uses: Number(maxUses.value) || 1,
    })
    emit('created')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    busy.value = false
  }
}

async function copyLink() {
  if (!inviteLink.value) return
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1800)
  } catch {
    // 剪贴板不可用时用户仍可手动选中下方输入框
  }
}
</script>

<template>
  <Dialog v-model="open" title="邀请协作者" description="链接仅在此处展示一次，请复制后发送" width="max-w-lg">
    <div v-if="!result" class="space-y-3">
      <div class="grid grid-cols-[110px_1fr] items-center gap-2">
        <label class="text-xs font-medium">渠道</label>
        <Select v-model="channel" :options="channelOptions" />
        <label class="text-xs font-medium">目标</label>
        <Input v-model="target" :placeholder="placeholders[channel]" />
        <label class="text-xs font-medium">有效天数</label>
        <Input v-model="expiresDays" type="number" min="1" max="90" />
        <label class="text-xs font-medium">可用次数</label>
        <Input v-model="maxUses" type="number" min="1" max="100" />
      </div>
      <PermissionMatrix v-model="permissions" />
      <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">
        {{ error }}
      </p>
    </div>

    <div v-else class="space-y-3">
      <div class="rounded-lg border border-primary/40 bg-accent/50 p-3 text-xs leading-relaxed text-foreground">
        <p class="flex items-center gap-1.5 font-medium"><Link2 class="h-3.5 w-3.5 text-primary" /> 邀请已创建</p>
        <p class="mt-1 text-muted-foreground">
          明文 token 只在此链接中出现，服务端仅保存哈希。关闭后将无法再次查看，请立即复制。
        </p>
      </div>
      <Input :model-value="inviteLink" readonly />
      <Button size="sm" @click="copyLink">
        <Check v-if="copied" class="h-3.5 w-3.5" /> <Copy v-else class="h-3.5 w-3.5" />
        {{ copied ? '已复制' : '复制链接' }}
      </Button>
    </div>

    <template #footer>
      <Button v-if="!result" variant="outline" size="sm" :disabled="busy" @click="open = false">取消</Button>
      <Button v-if="!result" size="sm" :disabled="busy || !target.trim()" @click="submit">
        <Loader2 v-if="busy" class="h-3.5 w-3.5 animate-spin" /> 创建邀请
      </Button>
      <Button v-else size="sm" @click="open = false">完成</Button>
    </template>
  </Dialog>
</template>
