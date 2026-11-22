<script setup lang="ts">
/**
 * 第 4 步：地图底图供应商。下拉只显示品牌名，选中后自动带出署名词与审图号（只读）；
 * 仅填写密钥，POST /wizard/test-map 只传 provider_id，连通性地址由后端预设带出。
 * 样式地址、瓦片模板、坐标系、署名与审图号一律不手填，也不展示任何合规免责声明。
 */
import { computed, ref, watch } from 'vue'
import { MapPinned, CheckCircle2 } from 'lucide-vue-next'
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
const selected = computed(() => MAP_PRESETS.find((p) => p.id === preset.value) ?? MAP_PRESETS[0])

watch(preset, (id) => {
  const m = props.form.map_providers[0]
  if (m) m.id = id
  props.form.map_default_provider_id = id
  props.probe.map.tested = false
  props.probe.map.ok = false
  props.probe.map.error = ''
})

async function test() {
  testing.value = true
  props.probe.map.error = ''
  props.probe.map.tested = true
  try {
    const r = await cfg.testMap({ provider_id: preset.value })
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
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <MapPinned class="mt-0.5 h-4 w-4 shrink-0" />
      <span>选择底图供应商后，署名词与审图号由系统自动带出；样式地址、瓦片模板与坐标系由服务端预设统一管理，无需填写。</span>
    </div>

    <div class="space-y-1.5">
      <label class="text-xs font-medium">底图供应商</label>
      <Select v-model="preset" :options="presetOptions" />
    </div>

    <!-- 只读元数据：审图号为空时按服务商公示 -->
    <div class="grid gap-2 rounded-lg border border-border bg-card p-3 sm:grid-cols-2">
      <div>
        <p class="text-[11px] text-muted-foreground">署名词</p>
        <p class="mt-0.5 break-all text-xs text-foreground">{{ selected.attribution || '按服务商公示' }}</p>
      </div>
      <div>
        <p class="text-[11px] text-muted-foreground">审图号</p>
        <p class="mt-0.5 text-xs text-foreground">{{ selected.auditNumber || '按服务商公示' }}</p>
      </div>
    </div>

    <div v-if="form.map_providers[0]" class="space-y-1.5">
      <label class="text-xs font-medium">密钥</label>
      <Input v-model="form.map_providers[0].key" type="password" placeholder="留空表示无需密钥或保留已配置密钥" autocomplete="new-password" />
      <p class="text-[11px] text-muted-foreground">密钥经加密后仅存于服务端，前端永不获取明文；免密钥供应商可留空。</p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" :disabled="testing" @click="test">
        {{ testing ? '探测中…' : '测试地图连通性' }}
      </Button>
      <span v-if="probe.map.ok" class="inline-flex items-center gap-1 text-xs text-primary">
        <CheckCircle2 class="h-3.5 w-3.5" /> {{ probe.map.skipped ? '已跳过（无可探测地址）' : `连通正常（状态码 ${probe.map.status}）` }}
      </span>
    </div>
    <p v-if="probe.map.error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ probe.map.error }}
    </p>
    <label v-if="probe.map.error || !probe.map.ok" class="flex items-center gap-2 text-xs text-muted-foreground">
      <input v-model="probe.map.skipped" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" />
      明确跳过地图连通性探测（离线环境或稍后再验证）
    </label>
  </div>
</template>
