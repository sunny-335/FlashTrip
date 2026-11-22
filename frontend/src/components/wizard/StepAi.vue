<script setup lang="ts">
/** 第 3 步：AI 供应商。base_url 来自可覆盖预设；模型名由 /models 探测下拉或手填，绝不硬编码。 */
import { computed, ref, watch } from 'vue'
import { Bot, CheckCircle2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import { AI_PRESETS, useConfigStore, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const cfg = useConfigStore()
const testing = ref(false)
const preset = ref(props.form.ai_providers[0]?.id ?? AI_PRESETS[0].id)

const presetOptions = AI_PRESETS.map((p) => ({ value: p.id, label: p.label }))
const modelOptions = computed(() => props.probe.ai.models.map((m) => ({ value: m, label: m })))

watch(preset, (id) => {
  const p = AI_PRESETS.find((x) => x.id === id)
  const provider = props.form.ai_providers[0]
  if (!provider) return
  provider.id = id
  if (p && p.base_url) provider.base_url = p.base_url
  props.probe.ai.models = []
  props.probe.ai.tested = false
  props.probe.ai.ok = false
})

async function probeModels() {
  const provider = props.form.ai_providers[0]
  if (!provider) return
  testing.value = true
  props.probe.ai.error = ''
  props.probe.ai.tested = true
  try {
    const r = await cfg.testAi({ base_url: provider.base_url, api_key: provider.api_key })
    props.probe.ai.ok = r.ok
    props.probe.ai.models = r.models ?? []
    if (r.ok && r.models.length && !provider.model) provider.model = r.models[0]
  } catch (e) {
    props.probe.ai.ok = false
    props.probe.ai.error = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <Bot class="mt-0.5 h-4 w-4 shrink-0" />
      <span>用原生 OpenAI 兼容三元组 (base_url / api_key / model) 接入。模型名通过 /models 动态探测，不预设任何具体型号；密钥加密存库、不回显前端。</span>
    </div>

    <label class="flex items-center gap-2 text-xs">
      <input v-model="probe.ai.skipped" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]" />
      暂不配置 AI（可稍后在设置中启用）
    </label>

    <div v-if="!probe.ai.skipped" class="space-y-3">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">供应商预设</label>
          <Select v-model="preset" :options="presetOptions" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">供应商 ID</label>
          <Input v-model="form.ai_providers[0].id" />
        </div>
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">Base URL（可覆盖）</label>
        <Input v-model="form.ai_providers[0].base_url" placeholder="https://.../v1" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">API Key</label>
        <Input v-model="form.ai_providers[0].api_key" type="password" placeholder="sk-..." />
      </div>

      <div class="flex items-end gap-2">
        <div class="flex-1 space-y-1.5">
          <label class="text-xs font-medium">模型（探测结果下拉）</label>
          <Select v-model="form.ai_providers[0].model" :options="modelOptions" :disabled="!modelOptions.length" />
        </div>
        <Button variant="outline" size="sm" :disabled="testing" @click="probeModels">
          {{ testing ? '探测中…' : '探测模型' }}
        </Button>
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">或手动填写模型名</label>
        <Input v-model="form.ai_providers[0].model" placeholder="例如服务商控制台给出的模型 ID" />
      </div>

      <div v-if="probe.ai.ok" class="inline-flex items-center gap-1.5 text-xs text-primary">
        <CheckCircle2 class="h-3.5 w-3.5" /> 探测成功
        <Badge variant="outline">{{ probe.ai.models.length }} 个模型</Badge>
      </div>
      <div v-if="probe.ai.error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
        {{ probe.ai.error }}
      </div>
    </div>
  </div>
</template>
