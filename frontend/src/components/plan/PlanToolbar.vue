<script setup lang="ts">
/**
 * 看板顶部工具栏：撤销、添加一天、PDF / ICS 导出。
 * 导出模块由另一代理提供（src/lib/export.ts），用 import.meta.glob 容错探测：
 * 模块缺失或加载失败时按钮保持禁用，不影响看板本身。
 */
import { onMounted, ref } from 'vue'
import { Undo2, CalendarPlus, FileDown, CalendarClock, Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import { usePlanContext } from '@/composables/usePlanDnd'

const props = withDefaults(defineProps<{ tripId: string; title?: string }>(), { title: '' })
const { dnd } = usePlanContext()

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
    localError.value = `导出模块未提供 ${kind.toUpperCase()} 导出函数`
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
</script>

<template>
  <div class="border-b border-border bg-card px-3 py-2">
    <div class="flex flex-wrap items-center gap-2">
      <div class="mr-auto min-w-0">
        <h1 class="truncate text-sm font-semibold">{{ props.title || '行程规划' }}</h1>
        <p class="text-[11px] text-muted-foreground">拖拽排序 · 跨天 / 回池 · Ctrl+Z 撤销</p>
      </div>
      <Button variant="outline" size="sm" :disabled="!dnd.canUndo.value || dnd.busy.value" @click="dnd.undoLast">
        <Undo2 class="h-3.5 w-3.5" /> 撤销
      </Button>
      <Button variant="outline" size="sm" @click="addDay"><CalendarPlus class="h-3.5 w-3.5" /> 添加一天</Button>
      <Button
        variant="outline"
        size="sm"
        :disabled="!exportReady || exporting"
        :title="exportReady ? '导出 PDF 行程册' : '导出模块尚未就绪'"
        @click="run('pdf')"
      >
        <Loader2 v-if="exporting" class="h-3.5 w-3.5 animate-spin" />
        <FileDown v-else class="h-3.5 w-3.5" /> PDF
      </Button>
      <Button
        variant="outline"
        size="sm"
        :disabled="!exportReady || exporting"
        :title="exportReady ? '导出 ICS 日历' : '导出模块尚未就绪'"
        @click="run('ics')"
      >
        <CalendarClock class="h-3.5 w-3.5" /> ICS
      </Button>
    </div>
    <p v-if="dnd.error.value" class="mt-2 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-[11px] text-destructive">
      {{ dnd.error.value }}
    </p>
    <p v-if="localError" class="mt-2 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-1.5 text-[11px] text-destructive">
      {{ localError }}
    </p>
  </div>
</template>
