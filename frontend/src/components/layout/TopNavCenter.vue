<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const active = computed(() => route.path)
const tripFilter = computed(() => (route.query.filter as string) || 'all')

const items = [
  { label: '仪表盘', path: '/dashboard' },
  { label: '足迹', path: '/footprints' },
  { label: '记忆', path: '/memories' },
  { label: '行程', path: '/trips' },
]
</script>

<template>
  <nav class="mx-auto flex h-full items-center gap-1">
    <RouterLink
      v-for="item in items"
      :key="item.path"
      :to="item.path"
      class="rounded-lg px-4 py-1.5 text-sm transition-colors"
      :class="active.startsWith(item.path)
        ? 'bg-secondary font-medium text-foreground'
        : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
    >
      {{ item.label }}
    </RouterLink>
    <div v-if="active.startsWith('/trips') && !active.includes('/plan')" class="ml-1 flex items-center gap-0.5 rounded-lg border border-border p-0.5">
      <RouterLink
        v-for="f in [{ k: 'all', t: '全部' }, { k: 'active', t: '未完成' }, { k: 'completed', t: '已完成' }]"
        :key="f.k"
        :to="{ path: '/trips', query: { filter: f.k } }"
        class="rounded-md px-2.5 py-1 text-xs"
        :class="tripFilter === f.k ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground'"
      >{{ f.t }}</RouterLink>
    </div>
  </nav>
</template>
