<script setup lang="ts">
/**
 * 备份设置：定时配置、备份列表、立即备份 / 导入 / 删除 / 清理过期。
 * POST /backup/export 返回 zip 二进制，必须用原生 fetch + Blob 下载，
 * 不能走 api.post（会按 JSON 解包而失败）；导入用 api.upload 提交 multipart。
 */
import { onMounted, reactive, ref } from 'vue'
import { Archive, Save, Loader2, Download, Upload, Trash2, RefreshCw } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'

interface BackupConfig {
  enabled: boolean
  cron_hour: number
  retention: number
  include_uploads: boolean
}
interface BackupItem {
  id: string
  filename: string
  size: number
  kind: string
  status: string
  created_at: string
  checksum: string
  error: string | null
  storage_path: string
}

const form = reactive({ enabled: false, cron_hour: 3, retention: 7, include_uploads: true })
const items = ref<BackupItem[]>([])
const loading = ref(true)
const saving = ref(false)
const exporting = ref(false)
const importing = ref(false)
const pruning = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const notice = ref('')
const error = ref('')

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function flash(text: string) {
  notice.value = text
  window.setTimeout(() => { notice.value = '' }, 2600)
}
function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
function formatTime(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN')
}
function kindLabel(kind: string): string {
  if (kind === 'manual') return '手动备份'
  if (kind === 'scheduled') return '定时备份'
  if (kind === 'import') return '导入前快照'
  return kind
}

async function loadConfig() {
  const cfg = await api.get<BackupConfig>('/backup/config')
  form.enabled = Boolean(cfg.enabled)
  form.cron_hour = cfg.cron_hour ?? 3
  form.retention = cfg.retention ?? 7
  form.include_uploads = Boolean(cfg.include_uploads)
}
async function loadList() {
  items.value = await api.get<BackupItem[]>('/backup/list').catch(() => [])
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadConfig(), loadList()])
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    await api.put('/backup/config', {
      enabled: form.enabled,
      cron_hour: Math.min(23, Math.max(0, Number(form.cron_hour) || 0)),
      retention: Math.max(1, Number(form.retention) || 7),
      include_uploads: form.include_uploads,
    })
    flash('备份配置已保存')
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    saving.value = false
  }
}

function filenameFromDisposition(value: string | null): string {
  const matched = value ? /filename="?([^";]+)"?/i.exec(value) : null
  return matched?.[1] || `flashtrip-backup-${Date.now()}.zip`
}

/** 二进制 zip 导出：原生 fetch 拿 Blob，再用临时链接触发下载。 */
async function exportBackup() {
  if (exporting.value) return
  exporting.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/v1/backup/export', {
      method: 'POST',
      credentials: 'same-origin',
    })
    if (!resp.ok) {
      let reason = `备份导出失败（状态码 ${resp.status}）`
      try {
        const body = await resp.json() as { message?: string }
        if (body?.message) reason = body.message
      } catch {
        // 非 JSON 错误响应，保留状态码提示
      }
      throw new Error(reason)
    }
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filenameFromDisposition(resp.headers.get('Content-Disposition'))
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    flash('备份已生成并开始下载')
    await loadList()
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    exporting.value = false
  }
}

/** 导入备份：multipart 字段名固定为 file。 */
async function onImportFile(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  importing.value = true
  error.value = ''
  try {
    const body = new FormData()
    body.append('file', file)
    await api.upload('/backup/import', body)
    flash('备份导入成功')
    await loadList()
  } catch (err) {
    error.value = messageOf(err)
  } finally {
    importing.value = false
    target.value = ''
  }
}

async function remove(item: BackupItem) {
  if (!window.confirm(`确定删除备份「${item.filename}」吗？此操作不可撤销。`)) return
  error.value = ''
  try {
    await api.del(`/backup/${encodeURIComponent(item.id)}`)
    flash('备份已删除')
    await loadList()
  } catch (e) {
    error.value = messageOf(e)
  }
}

async function prune() {
  if (pruning.value) return
  pruning.value = true
  error.value = ''
  try {
    const res = await api.post<{ pruned: number }>('/backup/prune')
    flash(`已清理 ${res.pruned ?? 0} 份过期备份`)
    await loadList()
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    pruning.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ error }}</p>
    <p v-if="notice" class="rounded-md border border-primary/40 bg-accent px-2.5 py-2 text-xs text-accent-foreground">{{ notice }}</p>

    <!-- 定时配置 -->
    <Card class="space-y-3">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Archive class="h-4 w-4 text-primary" /> 备份
          </h2>
          <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
            定时备份会在指定时刻生成压缩归档；也可随时手动导出或从归档恢复。
          </p>
        </div>
        <Button size="sm" :disabled="saving || loading" @click="save">
          <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
          <Save v-else class="h-3.5 w-3.5" /> 保存
        </Button>
      </div>

      <p v-if="loading" class="text-xs text-muted-foreground">正在读取备份配置…</p>
      <template v-else>
        <label class="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-sm text-foreground">
          <input v-model="form.enabled" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          启用定时备份
        </label>
        <div class="grid gap-2 sm:grid-cols-2">
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">每日备份时刻（0–23 时）</label>
            <Input v-model="form.cron_hour" type="number" min="0" max="23" placeholder="3" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">保留份数</label>
            <Input v-model="form.retention" type="number" min="1" placeholder="7" />
          </div>
        </div>
        <label class="flex items-center gap-2 text-xs text-foreground">
          <input v-model="form.include_uploads" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" />
          备份中包含上传的附件文件
        </label>
      </template>
    </Card>

    <!-- 操作区 -->
    <Card class="space-y-2">
      <h3 class="text-sm font-semibold text-foreground">备份操作</h3>
      <div class="flex flex-wrap gap-2">
        <Button size="sm" :disabled="exporting" @click="exportBackup">
          <Loader2 v-if="exporting" class="h-3.5 w-3.5 animate-spin" />
          <Download v-else class="h-3.5 w-3.5" /> 立即备份
        </Button>
        <Button variant="outline" size="sm" :disabled="importing" @click="fileInput?.click()">
          <Loader2 v-if="importing" class="h-3.5 w-3.5 animate-spin" />
          <Upload v-else class="h-3.5 w-3.5" /> 导入备份
        </Button>
        <Button variant="outline" size="sm" :disabled="pruning" @click="prune">
          <RefreshCw v-if="pruning" class="h-3.5 w-3.5 animate-spin" />
          <Trash2 v-else class="h-3.5 w-3.5" /> 清理过期
        </Button>
        <input ref="fileInput" type="file" accept=".zip" class="hidden" @change="onImportFile" />
      </div>
      <p class="text-[11px] leading-relaxed text-muted-foreground">
        「立即备份」会生成压缩归档并下载到本机；「导入备份」会先自动生成一份导入前快照，再恢复归档内容。
      </p>
    </Card>

    <!-- 备份列表 -->
    <Card class="space-y-2">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">备份列表</h3>
        <Button variant="ghost" size="sm" @click="loadList"><RefreshCw class="h-3.5 w-3.5" /> 刷新</Button>
      </div>
      <div v-if="items.length" class="space-y-1.5">
        <div v-for="item in items" :key="item.id" class="flex items-start justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-2 text-xs">
          <div class="min-w-0">
            <p class="truncate font-medium text-foreground">{{ item.filename }}</p>
            <p class="mt-0.5 text-[11px] text-muted-foreground">
              {{ formatTime(item.created_at) }} · {{ formatSize(item.size) }} · {{ kindLabel(item.kind) }}
            </p>
            <p v-if="item.error" class="mt-0.5 truncate text-[11px] text-destructive">{{ item.error }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <Badge :variant="item.status === 'ok' ? 'default' : 'destructive'">
              {{ item.status === 'ok' ? '正常' : '异常' }}
            </Badge>
            <button
              type="button"
              class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"
              title="删除该备份"
              @click="remove(item)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
      <p v-else class="text-xs text-muted-foreground">暂无备份记录。</p>
    </Card>
  </div>
</template>
