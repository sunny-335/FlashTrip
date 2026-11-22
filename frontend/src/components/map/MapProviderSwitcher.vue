<script setup lang="ts">
/** 底图下拉：只列出 /map/providers 返回的脱敏项，未 enabled 项禁用（Mapbox 未填 token 时不可选）。 */
import { computed } from 'vue'
import { Layers3 } from 'lucide-vue-next'
import type { MapProvider } from '@/stores/map'
import Select from '@/components/ui/Select.vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    providers: MapProvider[]
    switching?: boolean
    coordLabel?: string
  }>(),
  { switching: false, coordLabel: '' },
)
const emit = defineEmits<{ change: [id: string] }>()

const options = computed(() => props.providers.map((p) => ({ ...p, text: labelOf(p) })))

function labelOf(p: MapProvider): string {
  if (p.enabled) return p.label
  if (p.needsToken && !p.hasKey) return `${p.label}（未配置 Token）`
  return `${p.label}（未启用）`
}

function onPick(id: string) {
  const p = props.providers.find((x) => x.id === id)
  if (!p || !p.enabled || id === props.modelValue) return
  emit('change', id)
}
</script>

<template>
  <div class="rounded-lg border border-border bg-card/95 p-2 shadow-sm">
    <label class="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-foreground">
      <Layers3 class="h-3.5 w-3.5 text-primary" /> 底图
    </label>
    <Select :model-value="modelValue" :disabled="switching" @update:model-value="onPick">
      <option value="" disabled>选择底图…</option>
      <option
        v-for="p in options"
        :key="p.id"
        :value="p.id"
        :disabled="!p.enabled"
      >{{ p.text }}</option>
    </Select>
    <p v-if="coordLabel" class="mt-1.5 text-[10px] leading-tight text-muted-foreground">
      坐标系 {{ coordLabel }} · 密钥仅存于后端
    </p>
  </div>
</template>
