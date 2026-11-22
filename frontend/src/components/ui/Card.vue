<script setup lang="ts">
/** 简化版卡片容器：暖白底、细边框、克制阴影。 */
import { cn } from '@/lib/utils'
withDefaults(defineProps<{ padded?: boolean }>(), { padded: true })
</script>

<template>
  <div :class="cn('rounded-lg border border-border bg-card shadow-sm', padded && 'p-4')">
    <slot />
  </div>
</template>
