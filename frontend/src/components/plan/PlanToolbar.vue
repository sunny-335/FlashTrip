<script setup lang="ts">
/**
 * 看板顶部工具栏：撤销、添加一天、天气与出行建议、删除行程、PDF / ICS 导出。
 * 导出模块由另一代理提供（src/lib/export.ts），用 import.meta.glob 容错探测：
 * 模块缺失或加载失败时按钮保持禁用，不影响看板本身。
 */
import { onMounted, ref } from 'vue'
import { Undo2, CalendarPlus, FileDown, CalendarClock, Loader2, CloudSun, Trash2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Dialog from '@/components/ui/Dialog.vue'
import { usePlanContext } from '@/composables/usePlanDnd'
import { usePlanStore } from '@/stores/plan'
import type { WeatherAdviceResult } from '@/stores/plan'

const props = withDefaults(defineProps<{ tripId: string; title?: string }>(), { title: '' })
const emit = defineEmits<{ requestDeleteTrip: [] }>()
const { dnd } = usePlanContext()
const plan = usePlanStore()

type ExportFn = (tripId: string) => void | Promise<void>
// 字面量 glob：文件不存在时返回空对象（不会像静态 import 那样构建期报错）
const exporters = import.meta.glob('../../lib/export.ts')
const exporter = ref<Record<string, unknown> | null>(null)
const exportReady = ref(false)
const exporting = ref(false)
const localError = ref('')

onMounted(async () => {
  const loader = Object.values(exporters)[0]
  if (!loader) return
  try {
    const mod = (await loader()) as Record<string, unknown>
    exporter.value = mod
    exportReady.value = true
  } catch {
    exportReady.value = false
  }
})

/** 兼容导出模块可能采用的函数名，找不到的情况给出明确提示。 */
function pick(names: string[]): ExportFn | null {
  const mod = exporter.value
  if (!mod) return null
  for (const n of names) {
    if (typeof mod[n] === 'function') return mod[n] as ExportFn
  }
  return null
}

async function run(kind: 'pdf' | 'ics') {
  const fn = pick(
    kind === 'pdf'
      ? ['exportPdf', 'downloadPdf', 'exportTripPdf', 'toPdf', 'pdf']
      : ['exportIcs', 'downloadIcs', 'exportICS', 'exportTripIcs', 'toIcs', 'ics'],
  )
  if (!fn) {
    localError.value = '导出模块尚未提供对应的导出函数'
    return
  }
  exporting.value = true
  localError.value = ''
  try {
    await fn(props.tripId)
  } catch (e) {
    localError.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    exporting.value = false
  }
}

async function addDay() {
  try {
    await dnd.addDay({})
    localError.value = ''
  } catch (e) {
    localError.value = e instanceof ApiError ? e.message : (e as Error).message
  }
}

// ---------------------------------------------------------------- 天气与出行建议
const weatherOpen = ref(false)
const weatherBusy = ref(false)
const weatherError = ref('')
const weatherResult = ref<WeatherAdviceResult | null>(null)

/** 把 sent / failed 统一转成中文计数：可能是数字，也可能是收件人列表。 */
function countLabel(v: unknown): string {
  if (Array.isArray(v)) return String(v.length)
  if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  return '0'
}

/** 建议正文：字符串直接显示，数组逐条换行，其余转成可读文本。 */
function adviceText(v: unknown): string {
  if (v == null || v === '') return '暂无出行建议'
  if (typeof v === 'string') return v
  if (Array.isArray(v)) return v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('\n')
  return JSON.stringify(v, null, 2)
}

async function weatherAdvice() {
  weatherOpen.value = true
  weatherBusy.value = true
  weatherError.value = ''
  weatherResult.value = null
  try {
    weatherResult.value = await plan.weatherAdvice()
  } catch (e) {
    weatherError.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    weatherBusy.value = false
  }
}
</script>

<template>
  <div class="border-b border-border bg-card px-3 py-2">
    <div class="flex flex-wrap items-center gap-2">
      <div class="mr-auto min-w-0">
        <h1 class="truncate text-sm font-semibold">{{ props.title || '行程规划' }}</h1>
        <p class="text-[11px] text-muted-foreground">拖拽排序 · 点击卡片修改 · Ctrl+S 保存 · Ctrl+N 新建 · Ctrl+Z 撤销 · 离开自动保存</p>
      </div>
      <Button variant="outline" size="sm" :disabled="!dnd.canUndo.value || dnd.busy.value" @click="dnd.undoLast">
        <Undo2 class="h-3.5 w-3.5" /> 撤销
      </Button>
      <Button variant="outline" size="sm" @click="addDay"><CalendarPlus class="h-3.5 w-3.5" /> 添加一天</Button>
      <Button variant="outline" size="sm" :disabled="weatherBusy" @click="weatherAdvice">
        <Loader2 v-if="weatherBusy" class="h-3.5 w-3.5 animate-spin" />
        <CloudSun v-else class="h-3.5 w-3.5" />
        天气与出行建议
      </Button>
      <Button
        variant="outline"
        size="sm"
        :disabled="!exportReady || exporting"
        :title="exportReady ? '导出 PDF 行程册' : '导出模块尚未就绪'"
        @click="run('pdf')"
      >
        <Loader2 v-if="exporting" class="h-3.5 w-3.5 animate-spin" />
        <FileDown v-else class="h-3.5 w-3.5" /> 导出 PDF
      </Button>
      <Button
        variant="outline"
        size="sm"
        :disabled="!exportReady || exporting"
        :title="exportReady ? '导出 ICS 日历' : '导出模块尚未就绪'"
        @click="run('ics')"
      >
        <CalendarClock class="h-3.5 w-3.5" /> 导出 ICS
      </Button>
      <Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" @click="emit('requestDeleteTrip')">
        <Trash2 class="h-3.5 w-3.5" /> 删除行程
      </Button>
    </div>
    <p v-if="dnd.error.value" class="mt-2 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-[11px] text-destructive">
      {{ dnd.error.value }}
    </p>
    <p v-if="localError" class="mt-2 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-[11px] text-destructive">
      {{ localError }}
    </p>
  </div>

  <!-- 天气与出行建议结果：邮件发送概况 + 建议正文 -->
  <Dialog v-model="weatherOpen" title="天气与出行建议" description="生成出行天气建议并发送邮件" width="max-w-md">
    <div class="space-y-3">
      <p v-if="weatherBusy" class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 class="h-3.5 w-3.5 animate-spin" /> 正在生成出行建议…
      </p>
      <p v-if="weatherError" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">{{ weatherError }}</p>
      <template v-if="weatherResult">
        <p class="text-xs text-foreground">
          邮件已发送 <span class="font-semibold text-primary">{{ countLabel(weatherResult.sent) }}</span> 封，
          发送失败 <span class="font-semibold" :class="countLabel(weatherResult.failed) === '0' ? 'text-foreground' : 'text-destructive'">{{ countLabel(weatherResult.failed) }}</span> 封。
        </p>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">出行建议</label>
          <div class="max-h-60 whitespace-pre-wrap overflow-y-auto rounded-lg border border-border bg-muted/30 px-2.5 py-2 text-xs leading-relaxed text-foreground">
            {{ adviceText(weatherResult.advice) }}
          </div>
        </div>
      </template>
    </div>
    <template #footer>
      <Button variant="outline" size="sm" @click="weatherOpen = false">关闭</Button>
    </template>
  </Dialog>
</template>
