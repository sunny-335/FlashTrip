<script setup lang="ts">
/** 简化版徽标：用于类型 / 状态标记。 */
import { computed } from 'vue'
import { cn } from '@/lib/utils'

type Variant = 'default' | 'secondary' | 'outline' | 'destructive'
const props = withDefaults(defineProps<{ variant?: Variant }>(), { variant: 'secondary' })

const variants: Record<Variant, string> = {
  default: 'bg-primary text-primary-foreground',
  secondary: 'bg-secondary text-secondary-foreground',
  outline: 'border border-border text-foreground',
  destructive: 'bg-destructive text-destructive-foreground',
}
const cls = computed(() =>
  cn('inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium leading-tight', variants[props.variant]),
)
</script>

<template>
  <span :class="cls"><slot /></span>
</template>
