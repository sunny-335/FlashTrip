<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import ToastHost from '@/components/common/ToastHost.vue'

const route = useRoute()
const standalone = computed(() => Boolean(route.meta.standalone))
</script>

<template>
  <AppShell v-if="!standalone">
    <RouterView />
  </AppShell>
  <RouterView v-else />
  <ToastHost />
</template>
