<script setup lang="ts">
/**
 * 地图配置：下拉只显示供应商品牌名，选中后自动带出署名词与审图号（只读）。
 * 仅提供密钥输入与启用开关，默认底图单选；保存 PUT /settings 的
 * { map_providers:[{id,key,enabled}], map_default_provider_id }。
 * 样式地址、瓦片模板、坐标系、署名与审图号一律由服务端预设管理，不在此手填。
 */
import { computed, onMounted, ref } from 'vue'
import { MapPinned, Save, Loader2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'

interface MapProviderItem {
  id: string
  label: string
  attribution: string
  auditNumber: string
  enabled: boolean
}
interface MapDraft extends MapProviderItem {
  key: string
}

const providers = ref<MapDraft[]>([])
const selectedId = ref('')
const defaultId = ref('')
const loading = ref(true)
const saving = ref(false)
const notice = ref('')
const error = ref('')

const supplierOptions = computed(() => providers.value.map((p) => ({ value: p.id, label: p.label })))
const selected = computed<MapDraft>(() =>
  providers.value.find((p) => p.id === selectedId.value)
  ?? { id: '', label: '', attribution: '', auditNumber: '', enabled: false, key: '' },
)

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function flash(text: string) {
  notice.value = text
  window.setTimeout(() => { notice.value = '' }, 2600)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [list, settings] = await Promise.all([
      api.get<MapProviderItem[]>('/map/providers'),
      api.get<{
        config?: { map?: { default_provider_id?: string } }
        map?: { default_provider_id?: string }
      }>('/settings'),
    ])
    providers.value = list.map((p) => ({
      id: p.id,
      label: p.label,
      attribution: p.attribution,
      auditNumber: p.auditNumber,
      enabled: p.enabled,
      key: '',
    }))
    const savedDefault = settings.config?.map?.default_provider_id
      || settings.map?.default_provider_id
      || ''
    defaultId.value = savedDefault && providers.value.some((p) => p.id === savedDefault)
      ? savedDefault
      : providers.value[0]?.id || ''
    selectedId.value = defaultId.value || providers.value[0]?.id || ''
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    loading.value = false
  }
}

function setKey(v: string | number) {
  const p = providers.value.find((x) => x.id === selectedId.value)
  if (p) p.key = String(v)
}
function onEnabledChange(e: Event) {
  const p = providers.value.find((x) => x.id === selectedId.value)
  if (p) p.enabled = (e.target as HTMLInputElement).checked
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    await api.put('/settings', {
      map_providers: providers.value.map((p) => ({ id: p.id, key: p.key, enabled: p.enabled })),
      map_default_provider_id: defaultId.value,
    })
    // 清空明文输入框：留空即保留服务端已保存的密文
    providers.value.forEach((p) => { p.key = '' })
    flash('地图配置已保存')
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <Card class="space-y-4">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
          <MapPinned class="h-4 w-4 text-primary" /> 地图
        </h2>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
          选择底图供应商并配置密钥。切换供应商后，署名词与审图号由系统自动带出；
          样式地址、瓦片模板与坐标系由服务端统一管理，无需填写。
        </p>
      </div>
      <Button size="sm" :disabled="saving || loading || !providers.length" @click="save">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        <Save v-else class="h-3.5 w-3.5" /> 保存
      </Button>
    </div>

    <p v-if="loading" class="text-xs text-muted-foreground">正在读取底图供应商…</p>
    <p v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ error }}</p>
    <p v-if="notice" class="rounded-md border border-primary/40 bg-accent px-2.5 py-2 text-xs text-accent-foreground">{{ notice }}</p>

    <template v-if="!loading && providers.length">
      <div class="space-y-1.5">
        <label class="text-xs font-medium text-foreground">底图供应商</label>
        <Select v-model="selectedId" :options="supplierOptions" />
      </div>

      <!-- 自动带出的只读元数据：审图号为空时按服务商公示 -->
      <div class="grid gap-2 rounded-lg border border-border bg-muted/40 p-3 sm:grid-cols-2">
        <div>
          <p class="text-[11px] text-muted-foreground">署名词</p>
          <p class="mt-0.5 break-all text-xs text-foreground">{{ selected.attribution || '按服务商公示' }}</p>
        </div>
        <div>
          <p class="text-[11px] text-muted-foreground">审图号</p>
          <p class="mt-0.5 text-xs text-foreground">{{ selected.auditNumber || '按服务商公示' }}</p>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-foreground">密钥</label>
          <Input
            :model-value="selected.key"
            type="password"
            placeholder="留空表示保留已配置的密钥"
            autocomplete="new-password"
            @update:model-value="setKey"
          />
        </div>
        <label class="flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs text-foreground">
          <input
            type="checkbox"
            class="h-3.5 w-3.5 accent-[var(--primary)]"
            :checked="selected.enabled"
            @change="onEnabledChange"
          />
          启用
        </label>
      </div>

      <div class="border-t border-border pt-3">
        <p class="mb-2 text-xs font-medium text-foreground">默认底图</p>
        <div class="grid gap-1.5 sm:grid-cols-2">
          <label
            v-for="p in providers"
            :key="p.id"
            class="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-foreground"
          >
            <input v-model="defaultId" type="radio" name="default-map" :value="p.id" class="h-3.5 w-3.5 accent-[var(--primary)]" />
            <span class="truncate">{{ p.label }}</span>
          </label>
        </div>
        <p class="mt-2 text-[11px] text-muted-foreground">默认底图用于新行程的地图初始化。</p>
      </div>
    </template>
    <p v-else-if="!loading" class="text-xs text-muted-foreground">暂未获取到底图供应商清单。</p>
  </Card>
</template>
