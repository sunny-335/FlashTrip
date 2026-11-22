<script setup lang="ts">
/** 简化版按钮：variant / size 对齐 shadcn 语义，原生 button 实现。 */
import { computed } from 'vue'
import { cn } from '@/lib/utils'

type Variant = 'default' | 'outline' | 'ghost' | 'destructive'
type Size = 'sm' | 'default'

const props = withDefaults(
  defineProps<{
    variant?: Variant
    size?: Size
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
  }>(),
  { variant: 'default', size: 'default', type: 'button', disabled: false },
)

const base =
  'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 whitespace-nowrap select-none'
const variants: Record<Variant, string> = {
  default: 'bg-primary text-primary-foreground hover:bg-primary/90',
  outline: 'border border-border bg-card text-foreground hover:bg-muted',
  ghost: 'text-foreground hover:bg-muted',
  destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
}
// 编辑/删除等高频操作需要足够点击区：sm 至少 36px 高，default 至少 40px 高
const sizes: Record<Size, string> = {
  sm: 'h-9 px-3 text-sm',
  default: 'h-10 px-4 text-sm',
}

const cls = computed(() => cn(base, variants[props.variant], sizes[props.size]))
</script>

<template>
  <!-- 继承透传：外部 class / @click 等自动合并到根 button -->
  <button :type="type" :disabled="disabled" :class="cls">
    <slot />
  </button>
</template>
