<script setup lang="ts">
/** 简化版输入框：原生 input + v-model，支持透传 type/placeholder 等原生属性。 */
import { cn } from '@/lib/utils'

const model = defineModel<string | number>({ default: '' })
withDefaults(
  defineProps<{ invalid?: boolean }>(),
  { invalid: false },
)
</script>

<template>
  <input
    v-model="model"
    :class="
      cn(
        'flex h-9 w-full rounded-lg border border-input bg-card px-3 py-1 text-sm text-foreground shadow-sm outline-none transition placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        invalid && 'border-destructive focus-visible:ring-destructive',
      )
    "
  />
</template>
