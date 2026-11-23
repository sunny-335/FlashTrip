<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { HardDrive, Loader2, Save } from 'lucide-vue-next'
import { api } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
interface StorageResponse { backend: string; oss: Record<string, string | number | boolean>; s3: Record<string, string | number | boolean> }
type StorageValues = { endpoint: string; endpoint_url: string; region: string; bucket: string; access_key_id: string; access_key_secret: string; public_base_url: string; presign_ttl_seconds: number; has_access_key_id: boolean; has_access_key_secret: boolean }
const toast = useToastStore()
const backend = ref('local')
const oss = reactive<StorageValues>({ endpoint: '', endpoint_url: '', region: '', bucket: '', access_key_id: '', access_key_secret: '', public_base_url: '', presign_ttl_seconds: 604800, has_access_key_id: false, has_access_key_secret: false })
const s3 = reactive<StorageValues>({ ...oss })
const loading = ref(true)
const ready = ref(false)
const saving = ref(false)
const options = [{ value: 'local', label: '本地存储' }, { value: 'oss', label: '阿里云 OSS' }, { value: 's3', label: 'S3 兼容存储' }]
function assign(target: StorageValues, source: Record<string, string | number | boolean> | undefined) {
  if (!source) return
  for (const key of ['endpoint', 'endpoint_url', 'region', 'bucket', 'public_base_url', 'presign_ttl_seconds', 'has_access_key_id', 'has_access_key_secret'] as const) {
    const value = source[key]
    if (value !== undefined) (target as unknown as Record<string, unknown>)[key] = value
  }
  target.access_key_id = ''
  target.access_key_secret = ''
}
async function load() {
  loading.value = true
  ready.value = false
  try {
    const config = await api.get<StorageResponse>('/settings/storage')
    backend.value = config.backend
    assign(oss, config.oss)
    assign(s3, config.s3)
    ready.value = true
  } catch (e) { toast.error(e instanceof Error ? e.message : '存储配置读取失败') }
  finally { loading.value = false }
}
async function save() {
  if (saving.value || !ready.value) return
  saving.value = true
  try {
    await api.put('/settings/storage', { backend: backend.value, oss: { endpoint: oss.endpoint, region: oss.region, bucket: oss.bucket, access_key_id: oss.access_key_id, access_key_secret: oss.access_key_secret, public_base_url: oss.public_base_url, presign_ttl_seconds: Number(oss.presign_ttl_seconds) }, s3: { endpoint_url: s3.endpoint_url, region: s3.region, bucket: s3.bucket, access_key_id: s3.access_key_id, access_key_secret: s3.access_key_secret, public_base_url: s3.public_base_url, presign_ttl_seconds: Number(s3.presign_ttl_seconds) } })
    toast.success('存储配置已保存')
    await load()
  } catch (e) { toast.error(e instanceof Error ? e.message : '存储配置保存失败') }
  finally { saving.value = false }
}
onMounted(load)
</script>
<template>
  <Card class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h2 class="flex items-center gap-2 text-sm font-semibold"><HardDrive class="h-4 w-4 text-primary" /> 对象存储</h2><p class="mt-1 text-xs text-muted-foreground">密钥留空保留服务端原值；前端只读取已配置状态。</p></div><Button size="sm" :disabled="loading || saving || !ready" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /><Save v-else class="h-3.5 w-3.5" /> 保存</Button></div>
    <p v-if="loading" class="text-xs text-muted-foreground">正在读取配置…</p><Button v-else-if="!ready" variant="outline" size="sm" @click="load">重新读取</Button>
    <fieldset v-else :disabled="saving" class="min-w-0 space-y-3"><label class="block space-y-1 text-xs">存储后端<Select v-model="backend" :options="options" /></label>
      <p v-if="backend === 'local'" class="text-xs text-muted-foreground">文件存储在服务端本地 uploads 目录；对象存储仅影响新上传文件。</p>
      <template v-if="backend === 'oss'"><h3 class="text-xs font-semibold">阿里云 OSS</h3><div class="grid gap-3 sm:grid-cols-2"><label class="space-y-1 text-xs">Endpoint<Input v-model="oss.endpoint" /></label><label class="space-y-1 text-xs">Region（必填）<Input v-model="oss.region" /></label><label class="space-y-1 text-xs">Bucket<Input v-model="oss.bucket" /></label><label class="space-y-1 text-xs">Access Key ID<Input v-model="oss.access_key_id" type="password" autocomplete="new-password" placeholder="留空保留" /><span class="block text-[10px] text-muted-foreground">{{ oss.has_access_key_id ? '服务端已配置' : '尚未配置' }}</span></label><label class="space-y-1 text-xs">Access Key Secret<Input v-model="oss.access_key_secret" type="password" autocomplete="new-password" placeholder="留空保留" /><span class="block text-[10px] text-muted-foreground">{{ oss.has_access_key_secret ? '服务端已配置' : '尚未配置' }}</span></label><label class="space-y-1 text-xs">公有访问基础 URL（可选）<Input v-model="oss.public_base_url" /></label><label class="space-y-1 text-xs">预签名有效期（秒）<Input v-model="oss.presign_ttl_seconds" type="number" min="1" /></label></div></template>
      <template v-if="backend === 's3'"><h3 class="text-xs font-semibold">S3 兼容服务</h3><div class="grid gap-3 sm:grid-cols-2"><label class="space-y-1 text-xs">Endpoint URL（可选）<Input v-model="s3.endpoint_url" /></label><label class="space-y-1 text-xs">Region（可选）<Input v-model="s3.region" /></label><label class="space-y-1 text-xs">Bucket<Input v-model="s3.bucket" /></label><label class="space-y-1 text-xs">Access Key ID<Input v-model="s3.access_key_id" type="password" autocomplete="new-password" placeholder="留空保留" /><span class="block text-[10px] text-muted-foreground">{{ s3.has_access_key_id ? '服务端已配置' : '尚未配置' }}</span></label><label class="space-y-1 text-xs">Access Key Secret<Input v-model="s3.access_key_secret" type="password" autocomplete="new-password" placeholder="留空保留" /><span class="block text-[10px] text-muted-foreground">{{ s3.has_access_key_secret ? '服务端已配置' : '尚未配置' }}</span></label><label class="space-y-1 text-xs">公有访问基础 URL（可选）<Input v-model="s3.public_base_url" /></label><label class="space-y-1 text-xs">预签名有效期（秒）<Input v-model="s3.presign_ttl_seconds" type="number" min="1" /></label></div></template>
    </fieldset>
  </Card>
</template>
