<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Archive, Save, Loader2, Download, Plus, RefreshCw } from 'lucide-vue-next'
import { api, readError } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'

interface BackupConfig { enabled: boolean; cron_hour: number; retention: number; include_uploads: boolean }
interface BackupItem {
  id: string
  filename: string
  size: number
  created_at: string
  checksum: string
  download_url: string
}
const toast = useToastStore()
const form = reactive<BackupConfig>({ enabled: false, cron_hour: 3, retention: 7, include_uploads: true })
const items = ref<BackupItem[]>([])
const loading = ref(true)
const ready = ref(false)
const saving = ref(false)
const creating = ref(false)
const refreshing = ref(false)
const downloading = ref('')

async function loadList() {
  refreshing.value = true
  try {
    items.value = await api.get<BackupItem[]>('/backup/list')
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '备份列表读取失败')
  } finally {
    refreshing.value = false
  }
}
async function load() {
  loading.value = true
  try {
    const cfg = await api.get<BackupConfig>('/backup/config')
    form.enabled = cfg.enabled
    form.cron_hour = cfg.cron_hour
    form.retention = cfg.retention
    form.include_uploads = cfg.include_uploads
    ready.value = true
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '备份配置读取失败')
  } finally {
    loading.value = false
  }
}
async function save() {
  if (saving.value || !ready.value) return
  const hour = Number(form.cron_hour)
  const retention = Number(form.retention)
  if (!Number.isInteger(hour) || hour < 0 || hour > 23 || !Number.isInteger(retention) || retention < 1) {
    toast.error('备份时刻须为 0–23 的整数，保留份数须为正整数')
    return
  }
  saving.value = true
  try {
    await api.put('/backup/config', { enabled: form.enabled, cron_hour: hour, retention, include_uploads: form.include_uploads })
    toast.success('备份配置已保存')
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '备份配置保存失败')
  } finally {
    saving.value = false
  }
}
async function createBackup() {
  if (creating.value) return
  creating.value = true
  try {
    // 创建返回 JSON 元信息，不是 ZIP；仅列表里的下载操作获取二进制。
    const item = await api.post<BackupItem>('/backup/export')
    items.value = [item, ...items.value.filter(existing => existing.id !== item.id)]
    toast.success('备份已创建，可在列表中下载')
    await loadList()
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '备份创建失败')
  } finally {
    creating.value = false
  }
}
async function download(item: BackupItem) {
  if (downloading.value) return
  downloading.value = item.id
  try {
    const response = await fetch(`/api/v1/backup/${encodeURIComponent(item.id)}/download`, { credentials: 'same-origin' })
    if (!response.ok) throw new Error((await readError(response)).message)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = item.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    toast.success('备份下载已开始')
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '备份下载失败')
  } finally {
    downloading.value = ''
  }
}
function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
onMounted(() => { void load(); void loadList() })
</script>

<template>
  <div class="space-y-4">
    <Card class="space-y-3">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Archive class="h-4 w-4 text-primary" /> 备份</h2>
          <p class="mt-1 text-xs text-muted-foreground">配置定时备份，或手动创建后从列表下载；本页不提供恢复、删除或清理操作。</p>
        </div>
        <Button size="sm" :disabled="saving || loading || !ready" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /><Save v-else class="h-3.5 w-3.5" /> 保存</Button>
      </div>
      <p v-if="loading" class="text-xs text-muted-foreground">正在读取备份配置…</p>
      <Button v-else-if="!ready" variant="outline" size="sm" @click="load">重新读取</Button>
      <fieldset v-else :disabled="saving" class="min-w-0 space-y-3">
        <label class="flex items-center gap-2 text-xs"><input v-model="form.enabled" type="checkbox" /> 启用定时备份</label>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="space-y-1 text-xs">每日备份时刻（服务端时间，0–23 时）<Input v-model="form.cron_hour" type="number" min="0" max="23" /></label>
          <label class="space-y-1 text-xs">保留份数<Input v-model="form.retention" type="number" min="1" /></label>
        </div>
        <label class="flex items-center gap-2 text-xs"><input v-model="form.include_uploads" type="checkbox" /> 包含本地上传附件（不包含远端对象存储文件）</label>
        <p class="text-[11px] text-muted-foreground">手动创建使用已保存配置；归档含配置文件，请妥善保管。当前服务仅归档 SQLite 数据库文件。</p>
      </fieldset>
    </Card>
    <Card class="space-y-3">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h3 class="text-sm font-semibold">备份列表</h3>
        <div class="flex flex-wrap gap-2">
          <Button size="sm" :disabled="creating" @click="createBackup"><Loader2 v-if="creating" class="h-3.5 w-3.5 animate-spin" /><Plus v-else class="h-3.5 w-3.5" /> 创建备份</Button>
          <Button variant="outline" size="sm" :disabled="refreshing" @click="loadList"><RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': refreshing }" /> 刷新</Button>
        </div>
      </div>
      <div v-for="item in items" :key="item.id" class="flex flex-col gap-2 rounded-lg border border-border p-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="min-w-0">
          <p class="break-all text-xs font-medium">{{ item.filename }}</p>
          <p class="mt-1 text-[11px] text-muted-foreground">{{ new Date(item.created_at).toLocaleString('zh-CN') }} · {{ formatSize(item.size) }}</p>
        </div>
        <Button variant="outline" size="sm" :disabled="Boolean(downloading)" @click="download(item)"><Loader2 v-if="downloading === item.id" class="h-3.5 w-3.5 animate-spin" /><Download v-else class="h-3.5 w-3.5" /> 下载</Button>
      </div>
      <p v-if="!items.length" class="text-xs text-muted-foreground">{{ refreshing ? '正在读取列表…' : '暂无备份记录' }}</p>
    </Card>
  </div>
</template>
