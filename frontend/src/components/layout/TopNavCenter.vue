<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const active = computed(() => route.path)

/** 顶部主导航只保留四项；行程筛选由行程页内部提供，此处不再附加子链。 */
const items = [
  { label: '仪表盘', path: '/dashboard' },
  { label: '足迹', path: '/footprints' },
  { label: '记忆', path: '/memories' },
  { label: '行程', path: '/trips' },
]
</script>

<template>
  <!-- 窄屏可横向滚动，不撑破顶部栏 -->
  <nav class="nav-scroll flex h-full w-full items-center gap-1 whitespace-nowrap">
    <RouterLink
      v-for="item in items"
      :key="item.path"
      :to="item.path"
      class="shrink-0 rounded-lg px-3 py-1.5 text-sm transition-colors sm:px-4"
      :class="active.startsWith(item.path)
        ? 'bg-secondary font-medium text-foreground'
        : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
    >
      {{ item.label }}
    </RouterLink>
  </nav>
</template>
