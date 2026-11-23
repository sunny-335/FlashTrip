<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MapPinned, Save, Loader2 } from 'lucide-vue-next'
import { api } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import MarkdownText from '@/components/common/MarkdownText.vue'

interface MapProvider {
  id: string
  label: string
  attribution: string
  auditNumber: string
  enabled: boolean
  tilesReady: boolean
  poiReady: boolean
  routeReady: boolean
}
interface CredentialState { fields: Record<string, boolean>; labels: Record<string, string> }
interface MapDraft extends MapProvider { fields: Record<string, string>; configured: Record<string, boolean> }
interface SavedMap { default_provider_id?: string; providers?: { id: string; enabled?: boolean }[] | Record<string, { enabled?: boolean }> }
const credentialFields: Record<string, { name: string; label: string }[]> = {
  amap: [
    { name: 'js_key', label: 'JS API Key（JS SDK）' },
    { name: 'security_js_code', label: '安全密钥 securityJscode' },
    { name: 'service_key', label: 'Web 服务 Key（POI / 地理编码 / 路线）' },
  ],
  tianditu: [
    { name: 'browser_tk', label: '浏览器端 tk（底图 / 中文注记）' },
    { name: 'server_key', label: '服务端 key（POI / 地理编码）' },
  ],
}
const toast = useToastStore()
const providers = ref<MapDraft[]>([])
const selectedId = ref('')
const defaultId = ref('')
const loading = ref(true)
const ready = ref(false)
const saving = ref(false)
const selected = computed(() => providers.value.find(p => p.id === selectedId.value))
const options = computed(() => providers.value.map(p => ({ value: p.id, label: p.label })))

async function load() {
  loading.value = true
  ready.value = false
  try {
    const [list, credentials, settings] = await Promise.all([
      api.get<MapProvider[]>('/map/providers'),
      api.get<{ providers: Record<string, CredentialState> }>('/map/credentials'),
      api.get<{ map: SavedMap }>('/settings'),
    ])
    const saved = settings.map.providers
    providers.value = list.filter(p => p.id !== 'baidu' && p.id !== 'tianditu-label').map(p => {
      const entry = Array.isArray(saved) ? saved.find(item => item.id === p.id) : saved?.[p.id]
      return {
        id: p.id, label: p.label, attribution: p.attribution, auditNumber: p.auditNumber,
        enabled: entry?.enabled ?? true, tilesReady: p.tilesReady, poiReady: p.poiReady, routeReady: p.routeReady,
        fields: Object.fromEntries((credentialFields[p.id] ?? []).map(field => [field.name, ''])),
        configured: Object.fromEntries((credentialFields[p.id] ?? []).map(field => [field.name, Boolean(credentials.providers[p.id]?.fields[field.name])])),
      }
    })
    defaultId.value = providers.value.some(p => p.id === settings.map.default_provider_id)
      ? settings.map.default_provider_id! : providers.value[0]?.id ?? ''
    if (!providers.value.some(p => p.id === selectedId.value)) selectedId.value = defaultId.value
    ready.value = true
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '地图配置读取失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value || !ready.value) return
  if (!providers.value.some(p => p.id === defaultId.value && p.enabled)) {
    toast.error('请启用所选默认底图')
    return
  }
  saving.value = true
  let changed = false
  try {
    for (const provider of providers.value) {
      // 此接口空字符串表示清除，因此留空字段必须省略，不能照搬普通配置接口。
      const fields = Object.fromEntries(Object.entries(provider.fields).map(([name, value]) => [name, value.trim()]).filter(([, value]) => value))
      if (!Object.keys(fields).length) continue
      const result = await api.put<{ provider_id: string; fields: Record<string, boolean> }>('/map/credentials', { provider_id: provider.id, fields })
      provider.configured = result.fields
      for (const name of Object.keys(fields)) provider.fields[name] = ''
      changed = true
    }
    await api.put('/settings', {
      map_providers: providers.value.map(p => ({ id: p.id, enabled: p.enabled })),
      map_default_provider_id: defaultId.value,
    })
    toast.success('地图配置已保存')
    await load()
  } catch (e) {
    toast.error(`${changed ? '部分凭据已保存，其余配置未完成：' : ''}${e instanceof Error ? e.message : '地图配置保存失败'}`)
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>

<template>
  <Card class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h2 class="flex items-center gap-2 text-sm font-semibold"><MapPinned class="h-4 w-4 text-primary" /> 地图</h2>
        <p class="mt-1 text-xs text-muted-foreground">选择地图供应商；底图元数据由服务端维护。</p>
      </div>
      <Button size="sm" :disabled="saving || loading || !ready || !providers.length" @click="save">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /><Save v-else class="h-3.5 w-3.5" /> 保存
      </Button>
    </div>
    <p v-if="loading" class="text-xs text-muted-foreground">正在读取地图配置…</p>
    <Button v-else-if="!ready" variant="outline" size="sm" @click="load">重新读取</Button>
    <fieldset v-else-if="selected" :disabled="saving" class="min-w-0 space-y-4">
      <label class="block space-y-1 text-xs">配置供应商<Select v-model="selectedId" :options="options" /></label>
      <div class="grid gap-2 rounded-lg border border-border p-3 text-xs sm:grid-cols-2">
        <p class="break-all">署名：{{ selected.attribution }}</p>
        <p>审图号：{{ selected.auditNumber || '按服务商公示' }}</p>
        <p>底图：{{ selected.tilesReady ? '已就绪' : '未就绪' }}</p>
        <p>POI：{{ selected.poiReady ? '已就绪' : '未就绪' }} · 路线：{{ selected.routeReady ? '已就绪' : '未就绪' }}</p>
      </div>
      <div v-for="field in credentialFields[selected.id]" :key="field.name" class="space-y-1">
        <label :for="`map-${field.name}`" class="text-xs">{{ field.label }}</label>
        <Input :id="`map-${field.name}`" v-model="selected.fields[field.name]" type="password" autocomplete="new-password" placeholder="留空保留原凭据" />
        <p class="text-[11px] text-muted-foreground">{{ selected.configured[field.name] ? '服务端已配置' : '尚未配置' }}</p>
      </div>
      <label class="flex items-center gap-2 text-xs"><input v-model="selected.enabled" type="checkbox" /> 启用此供应商</label>
      <label class="block space-y-1 text-xs">默认底图<Select v-model="defaultId" :options="options" /></label>
      <MarkdownText compact source="密钥只提交给服务端，不写入浏览器存储；留空保留原值。\n\n- 高德：在高德开放平台控制台分别申请 JS API Key、安全密钥和 Web 服务 Key，填入对应输入框。JS Key 不能替代 Web 服务 Key。\n- 天地图：在天地图开发资源控制台申请浏览器端 tk 和服务端 key，分别填入；底图与中文注记共用浏览器端 tk。\n- 请为浏览器凭据配置域名白名单；服务调用与瓦片密钥由后端处理。" />
    </fieldset>
  </Card>
</template>
