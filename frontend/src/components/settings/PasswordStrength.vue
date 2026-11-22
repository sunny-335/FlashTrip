<script setup lang="ts">
/**
 * 密码强度条：调用公开接口 /auth/password-strength，防抖 300ms 实时评估。
 * 展示 0–4 级强度、四条字符类别勾叉、连续串禁止提示与中文改进建议。
 * 供安装向导管理员步、登录页、设置页改密表单共用；每次评估通过 change 回传完整指标。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, X } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'

/** 强度完整指标，随 change 事件回传；父组件按需读取 meetsPolicy 等字段。 */
interface StrengthResult {
  score: number
  label: string
  hints: string[]
  valid: boolean
  lengthOk: boolean
  classCount: number
  hasSequence: boolean
  adminOk: boolean
  isAdmin: boolean
  meetsPolicy: boolean
}

const props = withDefaults(
  defineProps<{ password: string; isAdmin?: boolean }>(),
  { isAdmin: false },
)
const emit = defineEmits<{ change: [info: StrengthResult] }>()

const EMPTY: StrengthResult = {
  score: 0,
  label: '弱',
  hints: [],
  valid: false,
  lengthOk: false,
  classCount: 0,
  hasSequence: false,
  adminOk: false,
  isAdmin: false,
  meetsPolicy: false,
}

const info = ref<StrengthResult | null>(null)
const error = ref('')
let timer: number | undefined
let seq = 0

/** 本地按字符类别判定四类勾叉，口径与后端策略一致：非字母数字一律归特殊字符。 */
const classes = computed(() => {
  const p = props.password || ''
  return {
    lower: /[a-z]/.test(p),
    upper: /[A-Z]/.test(p),
    digit: /[0-9]/.test(p),
    special: /[^a-zA-Z0-9]/.test(p),
  }
})

const rules = computed(() => {
  const i = info.value
  return [
    { label: '长度 8–32 位', ok: i?.lengthOk ?? false },
    { label: '小写字母', ok: classes.value.lower },
    { label: '大写字母', ok: classes.value.upper },
    { label: '数字', ok: classes.value.digit },
    { label: '特殊字符', ok: classes.value.special },
    { label: '不含连续或重复字符串', ok: i ? !i.hasSequence : false },
  ]
})

/** 强度条配色：弱红、一般琥珀、较强与主色青绿，不使用渐变。 */
const barColor = computed(() => {
  const s = info.value?.score ?? 0
  if (s <= 1) return 'bg-destructive'
  if (s === 2) return 'bg-amber-500'
  if (s === 3) return 'bg-primary/70'
  return 'bg-primary'
})

async function evaluate() {
  const current = ++seq
  error.value = ''
  try {
    const res = await api.post<StrengthResult>('/auth/password-strength', {
      password: props.password,
      is_admin: props.isAdmin,
    })
    if (current !== seq) return
    info.value = res
    emit('change', res)
  } catch (e) {
    if (current !== seq) return
    error.value = e instanceof ApiError ? e.message : '密码强度评估失败，请稍后重试'
    const fallback: StrengthResult = { ...EMPTY, isAdmin: props.isAdmin }
    info.value = fallback
    emit('change', fallback)
  }
}

function schedule() {
  if (timer !== undefined) window.clearTimeout(timer)
  timer = window.setTimeout(() => { void evaluate() }, 300)
}

watch([() => props.password, () => props.isAdmin], schedule)
onMounted(() => { void evaluate() })
onBeforeUnmount(() => { if (timer !== undefined) window.clearTimeout(timer) })
</script>

<template>
  <div class="space-y-2.5 rounded-lg border border-border bg-muted/40 p-3">
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs font-medium text-foreground">密码强度</span>
      <span class="text-xs text-muted-foreground">
        {{ info ? `${info.label}（${info.score} / 4）` : '评估中…' }}
      </span>
    </div>

    <!-- 四段强度条：按分数着色，其余保持浅边框色 -->
    <div class="flex gap-1">
      <span
        v-for="n in 4"
        :key="n"
        class="h-1.5 flex-1 rounded-full"
        :class="n <= (info?.score ?? 0) ? barColor : 'bg-border'"
      />
    </div>

    <!-- 长度 / 四类字符 / 连续串共六条规则 -->
    <div class="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
      <span
        v-for="r in rules"
        :key="r.label"
        class="flex items-center gap-1 text-[11px]"
        :class="r.ok ? 'text-primary' : 'text-muted-foreground'"
      >
        <Check v-if="r.ok" class="h-3 w-3 shrink-0" />
        <X v-else class="h-3 w-3 shrink-0" />
        {{ r.label }}
      </span>
    </div>

    <p v-if="isAdmin" class="text-[11px] text-muted-foreground">
      管理员须包含大写、小写、数字、特殊字符。
    </p>
    <p v-if="info?.hasSequence" class="text-[11px] text-destructive">
      不得包含连续或重复字符串（如 1234、abcd、aaaa）。
    </p>
    <ul v-if="info?.hints?.length" class="space-y-0.5">
      <li v-for="(h, i) in info?.hints ?? []" :key="i" class="text-[11px] text-muted-foreground">· {{ h }}</li>
    </ul>
    <p v-if="!password" class="text-[11px] text-muted-foreground">输入密码后将实时评估强度。</p>
    <p v-if="error" class="text-[11px] text-destructive">{{ error }}</p>
    <p v-if="info && isAdmin && !info.meetsPolicy && password" class="text-[11px] font-medium text-destructive">
      未达到管理员密码标准，无法继续。
    </p>
  </div>
</template>
