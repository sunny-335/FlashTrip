<script setup lang="ts">
/** 空状态：图标 + 标题 + 说明 + 操作插槽。 */
import type { Component } from 'vue'

withDefaults(
  defineProps<{
    title: string
    description?: string
    icon?: Component
  }>(),
  { description: '' },
)
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card/50 px-6 py-10 text-center">
    <component :is="icon" v-if="icon" class="h-7 w-7 text-muted-foreground" />
    <div>
      <p class="text-sm font-medium text-foreground">{{ title }}</p>
      <p v-if="description" class="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
        {{ description }}
      </p>
    </div>
    <div v-if="$slots.default" class="mt-1"><slot /></div>
  </div>
</template>
