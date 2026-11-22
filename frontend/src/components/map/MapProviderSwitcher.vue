<script setup lang="ts">
/** 底图信息（中性纯展示组件）。
 *  行程规划页不再渲染本组件：底图只能在全局设置里配置，由设置页统一管理。
 *  保留文件与原有 props / 事件签名，避免历史 import 报错，也可供设置页复用为只读展示。
 */
import { computed } from 'vue'
import { Layers3 } from 'lucide-vue-next'
import type { MapProvider } from '@/stores/map'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    providers?: MapProvider[]
    switching?: boolean
    coordLabel?: string
  }>(),
  { modelValue: '', providers: () => [], switching: false, coordLabel: '' },
)

// 保留签名以兼容既有引用；本组件只展示信息，不提供切换交互
defineEmits<{ change: [id: string] }>()

const current = computed(() => props.providers.find((p) => p.id === props.modelValue) ?? null)
const enabledCount = computed(() => props.providers.filter((p) => p.enabled).length)
</script>

<template>
  <div class="rounded-lg border border-border bg-card/95 p-2.5 shadow-sm">
    <div class="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
      <Layers3 class="h-3.5 w-3.5 text-primary" /> 当前底图
      <span class="ml-auto text-[10px] font-normal text-muted-foreground">
        {{ switching ? '切换中' : '已就绪' }}
      </span>
    </div>
    <p class="mt-1.5 truncate text-xs font-semibold text-foreground">
      {{ current?.label || '未选择底图' }}
    </p>
    <p v-if="current?.attribution" class="mt-1 text-[10px] leading-tight text-muted-foreground">
      {{ current.attribution }}
    </p>
    <p class="mt-1.5 text-[10px] leading-tight text-muted-foreground">
      已启用 {{ enabledCount }} 个底图 · 在全局设置中更换
    </p>
  </div>
</template>
