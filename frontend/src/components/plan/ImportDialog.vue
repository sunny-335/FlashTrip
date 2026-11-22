<script setup lang="ts">
/**
 * 导入对话框：导入文件（json/csv/txt）/ 清单导入（粘贴清单）。
 * 前端解析为结构化 PlanItemCreate[]，用 keysBetween 生成合法 sort_key 后提交 /plan/import。
 */
import { computed, ref, watch } from 'vue'
import { Loader2, Upload } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import { keysBetween } from '@/lib/sortKey'
import Button from '@/components/ui/Button.vue'
import Dialog from '@/components/ui/Dialog.vue'
import { POOL_KEY, usePlanContext } from '@/composables/usePlanDnd'
import type { PlanItemCreate, PlanType } from '@/stores/plan'

const props = withDefaults(defineProps<{ mode?: 'file' | 'list' }>(), { mode: 'list' })
const open = defineModel<boolean>({ default: false })
const { dnd } = usePlanContext()

const text = ref('')
const fileName = ref('')
const importing = ref(false)
const error = ref('')

function normType(v: unknown): PlanType {
  const map: Record<string, PlanType> = {
    '地点': 'place', '景点': 'place', 'place': 'place', 'poi': 'place',
    '酒店': 'hotel', 'hotel': 'hotel', '住宿': 'hotel',
    '交通': 'transport', 'transport': 'transport', '航班': 'transport',
    '活动': 'activity', 'activity': 'activity',
    '备注': 'note', 'note': 'note',
  }
  return map[String(v ?? '').toLowerCase()] ?? 'place'
}

function normalizeRow(row: unknown): PlanItemCreate {
  const o = (row ?? {}) as Record<string, unknown>
  return {
    title: String(o.title ?? o.name ?? '').trim(),
    type: normType(o.type),
    subtitle: o.subtitle ? String(o.subtitle) : null,
    address: o.address ? String(o.address) : null,
    category: o.category ? String(o.category) : null,
    note: o.note ? String(o.note) : null,
    source: 'import',
    bucket: 'main',
    day_id: null,
  }
}

/** 支持 JSON 数组 / {items:[...]}，或每行「标题 | 类型 | 地址 | 分类」「标题,类型,地址,分类」。 */
function parseText(raw: string): PlanItemCreate[] {
  const t = raw.trim()
  if (!t) return []
  if (t.startsWith('[') || t.startsWith('{')) {
    try {
      const data = JSON.parse(t) as unknown
      const rows = Array.isArray(data)
        ? data
        : ((data as Record<string, unknown>).items as unknown[] | undefined) ?? []
      return rows.map(normalizeRow).filter((r) => r.title)
    } catch {
      // 不是合法 JSON 时按纯文本行解析
    }
  }
  const header = new Set(['title', '标题', 'name', '名称'])
  return t
    .split(/\r?\n/)
    .map((line) => (line.includes('|') ? line.split('|') : line.split(',')).map((s) => s.trim()))
    .filter((p) => p[0] && !header.has(p[0].toLowerCase()))
    .map((p) => ({
      title: p[0],
      type: normType(p[1] ?? ''),
      address: p[2] || null,
      category: p[3] || null,
      source: 'import',
      bucket: 'main',
      day_id: null,
    }))
}

const parsed = computed(() => parseText(text.value))

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  fileName.value = f.name
  try {
    text.value = await f.text()
    error.value = ''
  } catch (err) {
    error.value = (err as Error).message
  }
  input.value = ''
}

watch(open, (v) => {
  if (v) {
    text.value = ''
    fileName.value = ''
    error.value = ''
  }
})

async function submit() {
  if (!parsed.value.length) {
    error.value = '没有可导入的条目，请先上传文件或粘贴清单'
    return
  }
  error.value = ''
  importing.value = true
  let keys: string[]
  try {
    const existing = dnd.lists[POOL_KEY] ?? []
    const last = existing.length ? existing[existing.length - 1].sort_key : null
    keys = keysBetween(last, null, parsed.value.length)
  } catch (e) {
    error.value = `排序键计算失败：${(e as Error).message}，请刷新后重试`
    importing.value = false
    return
  }
  const items = parsed.value.map((it, i) => ({ ...it, sort_key: keys[i] }))
  try {
    await dnd.importItems(items)
    open.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <Dialog v-model="open" :title="props.mode === 'file' ? '导入文件' : '清单导入'" description="解析后统一进入待规划池，可再拖到各天">
    <div class="space-y-3">
      <div v-if="props.mode === 'file'" class="space-y-1.5">
        <label class="text-xs font-medium">选择文件（.json / .csv / .txt）</label>
        <label class="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border bg-card px-3 py-3 text-xs text-muted-foreground hover:bg-muted">
          <Upload class="h-4 w-4" />
          <span class="truncate">{{ fileName || '点击选择文件' }}</span>
          <input type="file" accept=".json,.csv,.txt,text/plain,application/json" class="hidden" @change="onFile" />
        </label>
      </div>

      <div class="space-y-1.5">
        <label class="text-xs font-medium">清单内容（可编辑）</label>
        <textarea
          v-model="text"
          rows="8"
          class="w-full rounded-lg border border-input bg-card px-3 py-2 font-mono text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="每行一条，或粘贴 JSON 数组；格式见下方说明"
        />
        <p class="text-[11px] leading-relaxed text-muted-foreground">
          支持「标题 | 类型 | 地址 | 分类」或 CSV 逗号分隔，例如「灵隐寺 | 地点 | 法云弄 | 景点」；
          JSON 数组或 {items:[...]} 亦可（字段 title / type / address / category）。
        </p>
      </div>

      <p class="text-xs">解析出 <span class="font-semibold text-primary">{{ parsed.length }}</span> 条</p>
      <div v-if="parsed.length" class="max-h-28 overflow-y-auto rounded-lg border border-border bg-muted/40 p-2 text-[11px] text-muted-foreground">
        <p v-for="(p, i) in parsed.slice(0, 8)" :key="i" class="truncate">{{ i + 1 }}. {{ p.title }}</p>
        <p v-if="parsed.length > 8">…以及另外 {{ parsed.length - 8 }} 条</p>
      </div>
      <div v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5 text-xs text-destructive">{{ error }}</div>
    </div>
    <template #footer>
      <Button variant="outline" size="sm" :disabled="importing" @click="open = false">取消</Button>
      <Button size="sm" :disabled="importing || !parsed.length" @click="submit">
        <Loader2 v-if="importing" class="h-3.5 w-3.5 animate-spin" />
        {{ importing ? '导入中…' : `导入 ${parsed.length} 条` }}
      </Button>
    </template>
  </Dialog>
</template>
