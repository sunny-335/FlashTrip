<script setup lang="ts">
/** 原生 select 包装：options 传 [{value,label}]，也支持默认插槽自定义 option。 */
import { cn } from '@/lib/utils'

defineProps<{
  options?: { value: string; label: string }[]
  invalid?: boolean
}>()
const model = defineModel<string>({ default: '' })
</script>

<template>
  <select
    v-model="model"
    :class="
      cn(
        'h-9 w-full rounded-lg border border-input bg-card px-2 text-sm text-foreground shadow-sm outline-none transition focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        invalid && 'border-destructive',
      )
    "
  >
    <slot>
      <option v-for="o in options ?? []" :key="o.value" :value="o.value">{{ o.label }}</option>
    </slot>
  </select>
</template>
