<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const title = computed(() => (route.meta.title as string) || '该模块')
</script>

<template>
  <section class="mx-auto max-w-xl px-6 py-20 text-center">
    <h1 class="text-lg font-medium text-foreground">{{ title }}</h1>
    <p class="mt-3 text-sm text-muted-foreground">该模块正在建设中，路由与接口契约已就绪。</p>
  </section>
</template>
