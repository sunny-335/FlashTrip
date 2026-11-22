<script setup lang="ts">
/** 第 4 步：地图供应商 + 审图号 + 合规提示。免 token 的 OpenFreeMap 为默认境外底图。 */
import { ref, watch } from 'vue'
import { MapPinned, ShieldAlert, CheckCircle2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import { MAP_PRESETS, useConfigStore, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const cfg = useConfigStore()
const testing = ref(false)
const preset = ref(props.form.map_providers[0]?.id ?? MAP_PRESETS[0].id)

const presetOptions = MAP_PRESETS.map((p) => ({ value: p.id, label: p.label }))
const coordOptions = [
  { value: 'WGS84', label: 'WGS84（GPS / OSM）' },
  { value: 'CGCS2000', label: 'CGCS2000（天地图）' },
  { value: 'GCJ-02', label: 'GCJ-02（高德）' },
  { value: 'BD-09', label: 'BD-09（百度）' },
]

watch(preset, (id) => {
  const p = MAP_PRESETS.find((x) => x.id === id)
  const m = props.form.map_providers[0]
  if (!m || !p) return
  m.id = p.id
  m.style_url = p.style_url
  m.tile_url_template = p.tile_url_template
  m.coord_system = p.coord_system
  m.attribution = p.attribution
  m.needs_token = p.needs_token
  props.form.map_default_provider_id = p.id
  props.probe.map.tested = false
  props.probe.map.ok = false
})

async function test() {
  const m = props.form.map_providers[0]
  if (!m) return
  testing.value = true
  props.probe.map.error = ''
  props.probe.map.tested = true
  try {
    const r = await cfg.testMap({ style_url: m.style_url, tile_url_template: m.tile_url_template, key: m.key })
    props.probe.map.ok = r.ok
    props.probe.map.status = r.status_code ?? 0
    props.probe.map.skipped = Boolean(r.skipped)
  } catch (e) {
    props.probe.map.ok = false
    props.probe.map.error = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
      <ShieldAlert class="mt-0.5 h-4 w-4 shrink-0" />
      <span>境外底图（OpenFreeMap / OSM / Mapbox）无中国审图号，仅建议用于境外行程或个人自用。面向境内公众服务请配置合规底图、审图号与 ICP 备案；本向导不声称已完成合规审查。</span>
    </div>

    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="space-y-1.5">
        <label class="text-xs font-medium">底图供应商</label>
        <Select v-model="preset" :options="presetOptions" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">坐标系</label>
        <Select v-model="form.map_providers[0].coord_system" :options="coordOptions" />
      </div>
    </div>
    <div class="space-y-1.5">
      <label class="text-xs font-medium">Style URL</label>
      <Input v-model="form.map_providers[0].style_url" placeholder="https://tiles.openfreemap.org/styles/liberty" />
    </div>
    <div class="space-y-1.5">
      <label class="text-xs font-medium">瓦片 URL 模板（raster 供应商）</label>
      <Input v-model="form.map_providers[0].tile_url_template" placeholder="可含 {key} / {token} 占位符" />
    </div>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="space-y-1.5">
        <label class="text-xs font-medium">Key / Token</label>
        <Input v-model="form.map_providers[0].key" type="password" placeholder="免 token 底图可留空" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">审图号</label>
        <Input v-model="form.audit_number" placeholder="境内合规底图必填，如 GS(2024)xxxx号" />
      </div>
    </div>
    <div class="space-y-1.5">
      <label class="text-xs font-medium">Attribution（署名词）</label>
      <Input v-model="form.map_providers[0].attribution" />
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" :disabled="testing" @click="test">
        {{ testing ? '探测中…' : '测试地图地址' }}
      </Button>
      <span v-if="probe.map.ok" class="inline-flex items-center gap-1 text-xs text-primary">
        <CheckCircle2 class="h-3.5 w-3.5" /> {{ probe.map.skipped ? '已跳过（未配置地址）' : `可达 HTTP ${probe.map.status}` }}
      </span>
    </div>
    <p v-if="probe.map.error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ probe.map.error }}
    </p>
    <label v-if="probe.map.error || !probe.map.ok" class="flex items-center gap-2 text-xs text-muted-foreground">
      <input v-model="probe.map.skipped" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" />
      明确跳过地图地址探测（离线环境或稍后再验证）
    </label>
    <p class="flex items-start gap-1.5 text-[11px] text-muted-foreground">
      <MapPinned class="mt-0.5 h-3.5 w-3.5 shrink-0" />
      业务坐标统一以 WGS84 入库并带 coord_system 标记，渲染时按底图坐标系反向转换。
    </p>
  </div>
</template>
