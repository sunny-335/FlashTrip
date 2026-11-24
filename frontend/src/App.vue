<script setup lang="ts">
/**
 * 应用外壳：安装状态未确认前只显示启动占位，避免首次部署时先闪出仪表盘框架
 * 再被路由守卫重定向到安装向导。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import ToastHost from '@/components/common/ToastHost.vue'
import { wizardStatus } from '@/router'

const route = useRoute()
const standalone = computed(() => Boolean(route.meta.standalone))
const booted = ref(false)

onMounted(async () => {
  // 与路由守卫共用同一份缓存探测；失败时守卫会放行到安装向导
  await wizardStatus()
  booted.value = true
})
</script>

<template>
  <div v-if="!booted" class="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
    正在加载…
  </div>
  <template v-else>
    <AppShell v-if="!standalone">
      <RouterView />
    </AppShell>
    <RouterView v-else />
  </template>
  <ToastHost />
</template>
