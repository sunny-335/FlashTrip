<script setup lang="ts">
/** 安装引导页（standalone）：已安装则回登录页，否则渲染七步向导。 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useConfigStore } from '@/stores/config'
import InstallWizard from '@/components/wizard/InstallWizard.vue'

const cfg = useConfigStore()
const router = useRouter()
const version = ref('')
const checking = ref(true)

onMounted(async () => {
  try {
    const s = await cfg.loadStatus()
    version.value = s.version
    if (s.installed) {
      await router.replace('/login')
      return
    }
  } catch {
    // 状态探测失败不阻断向导本身；具体错误在向导内由各步显示
  } finally {
    checking.value = false
  }
})
</script>

<template>
  <div class="flex min-h-screen items-start justify-center bg-background px-4 py-10 text-foreground">
    <div class="w-full max-w-2xl">
      <div class="mb-6 flex items-center gap-2.5">
        <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">瞬</span>
        <div>
          <h1 class="text-base font-semibold leading-tight">瞬旅 FlashTrip</h1>
          <p class="text-xs text-muted-foreground">首次启动 · 安装向导{{ version ? ` · v${version}` : '' }}</p>
        </div>
      </div>

      <div v-if="checking" class="rounded-lg border border-border bg-card p-10 text-center text-sm text-muted-foreground shadow-sm">
        正在检查安装状态…
      </div>
      <div v-else class="rounded-lg border border-border bg-card p-6 shadow-sm">
        <InstallWizard />
      </div>
      <p class="mt-4 text-center text-[11px] text-muted-foreground">
        配置写入 /data/config.json 与数据库双份；任一步失败会回滚半成品配置。
      </p>
    </div>
  </div>
</template>
