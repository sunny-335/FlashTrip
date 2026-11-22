<script setup lang="ts">
/** 分享链接创建：勾选包含内容 + 有效期 + 标题；生成后展示可复制完整链接与一次性只读令牌。
 *  费用默认不公开（include_expenses=false），与后端默认一致。
 */
import { computed, ref, watch } from 'vue'
import { Link2, Copy, Check, Loader2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Dialog from '@/components/ui/Dialog.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'

/** 创建分享的返回体：字段对齐 share_service.create_share。 */
interface ShareCreated {
  id: string
  token: string
  url: string
  title: string
  expires_at: string
}

const props = defineProps<{ tripId: string }>()
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ created: [] }>()

const title = ref('')
const expiresDays = ref(30)
const includeTransports = ref(true)
const includeBookings = ref(true)
const includePacking = ref(true)
const includeExpenses = ref(false)
const includeMoments = ref(false)
const busy = ref(false)
const error = ref('')
const result = ref<ShareCreated | null>(null)
const copied = ref(false)

/** 完整可分享链接：后端返回 /share/{token} 相对地址，补上当前站点域名。 */
const fullLink = computed(() => {
  if (!result.value) return ''
  const url = result.value.url || `/share/${result.value.token}`
  return `${window.location.origin}${url.startsWith('/') ? url : `/${url}`}`
})

watch(open, (v) => {
  if (v) {
    title.value = ''
    expiresDays.value = 30
    includeTransports.value = true
    includeBookings.value = true
    includePacking.value = true
    includeExpenses.value = false // 费用默认不公开
    includeMoments.value = false
    error.value = ''
    result.value = null
    copied.value = false
  }
})

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    result.value = await api.post<ShareCreated>(`/trips/${props.tripId}/shares`, {
      title: title.value.trim(),
      include_transports: includeTransports.value,
      include_bookings: includeBookings.value,
      include_packing: includePacking.value,
      include_expenses: includeExpenses.value,
      include_moments: includeMoments.value,
      expires_days: Number(expiresDays.value) || 30,
    })
    emit('created')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    busy.value = false
  }
}

async function copyLink() {
  if (!fullLink.value) return
  try {
    await navigator.clipboard.writeText(fullLink.value)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1800)
  } catch {
    // 剪贴板不可用时用户仍可手动选中下方输入框
  }
}
</script>

<template>
  <Dialog v-model="open" title="创建分享链接" description="生成公开只读链接，无需登录即可查看" width="max-w-lg">
    <div v-if="!result" class="space-y-3">
      <div class="grid grid-cols-[110px_1fr] items-center gap-2">
        <label class="text-xs font-medium">标题</label>
        <Input v-model="title" placeholder="例如：给家人的行程概览（可选）" />
        <label class="text-xs font-medium">有效期（天）</label>
        <Input v-model="expiresDays" type="number" min="1" max="365" />
      </div>

      <div class="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
        <p class="text-xs font-medium">链接包含的内容</p>
        <label class="flex min-h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="includeTransports" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" /> 包含交通
        </label>
        <label class="flex min-h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="includeBookings" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" /> 包含酒店预订
        </label>
        <label class="flex min-h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="includePacking" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" /> 包含物品清单
        </label>
        <label class="flex min-h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="includeExpenses" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" /> 包含费用
        </label>
        <label class="flex min-h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="includeMoments" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" /> 包含对外瞬间
        </label>
        <p class="text-[11px] leading-relaxed text-muted-foreground">
          费用默认不公开；旅途瞬间仅包含已设为「对外展示」的记录。
        </p>
      </div>

      <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive">{{ error }}</p>
    </div>

    <div v-else class="space-y-3">
      <div class="rounded-lg border border-primary/40 bg-accent/50 p-3 text-xs leading-relaxed text-foreground">
        <p class="flex items-center gap-1.5 font-medium"><Link2 class="h-3.5 w-3.5 text-primary" /> 分享链接已生成</p>
        <p class="mt-1 text-muted-foreground">这是公开只读链接，任何拿到它的人都能查看，请按需转发。令牌仅在此处完整展示一次。</p>
      </div>
      <div class="space-y-1">
        <label class="text-xs font-medium">完整链接</label>
        <Input :model-value="fullLink" readonly />
      </div>
      <div class="space-y-1">
        <label class="text-xs font-medium">只读令牌</label>
        <Input :model-value="result.token" readonly />
      </div>
      <Button size="sm" @click="copyLink">
        <Check v-if="copied" class="h-3.5 w-3.5" /> <Copy v-else class="h-3.5 w-3.5" />
        {{ copied ? '已复制' : '复制完整链接' }}
      </Button>
    </div>

    <template #footer>
      <Button v-if="!result" variant="outline" size="sm" :disabled="busy" @click="open = false">取消</Button>
      <Button v-if="!result" size="sm" :disabled="busy" @click="submit">
        <Loader2 v-if="busy" class="h-3.5 w-3.5 animate-spin" /> 生成链接
      </Button>
      <Button v-else size="sm" @click="open = false">完成</Button>
    </template>
  </Dialog>
</template>
