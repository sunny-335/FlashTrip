<script setup lang="ts">
/**
 * 设置页：左侧分组竖排导航（桌面常驻 / 手机平板横向标签）+ 右侧内容面板按选中项切换。
 * 各分区组件自治加载与保存：主题走 useUiStore，AI / 地图 / 瞬间可见性走 PUT /settings，
 * 邮件 / 天气 / 备份走各自专用接口。PUT /settings 已移除解锁门禁，登录后即可保存。
 */
import { computed, onMounted, ref, type Component } from 'vue'
import { Settings2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import SettingsSidebar from '@/components/settings/SettingsSidebar.vue'
import SettingsSectionAppearance from '@/components/settings/SettingsSectionAppearance.vue'
import SettingsSectionMoments from '@/components/settings/SettingsSectionMoments.vue'
import SettingsSectionAi from '@/components/settings/SettingsSectionAi.vue'
import SettingsSectionMap from '@/components/settings/SettingsSectionMap.vue'
import SettingsSectionAccount from '@/components/settings/SettingsSectionAccount.vue'
import MailSettings from '@/components/settings/MailSettings.vue'
import WeatherSettings from '@/components/settings/WeatherSettings.vue'
import BackupSettings from '@/components/settings/BackupSettings.vue'

const active = ref('appearance')
const version = ref('')
const loadError = ref('')

const componentsByKey: Record<string, Component> = {
  appearance: SettingsSectionAppearance,
  moments: SettingsSectionMoments,
  ai: SettingsSectionAi,
  map: SettingsSectionMap,
  weather: WeatherSettings,
  mail: MailSettings,
  account: SettingsSectionAccount,
  backup: BackupSettings,
}
const current = computed(() => componentsByKey[active.value] ?? SettingsSectionAppearance)

async function load() {
  try {
    const s = await api.get<{ version?: string }>('/settings')
    version.value = s.version || ''
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : '系统配置读取失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-[1080px] px-5 py-6">
    <div class="mb-5">
      <h1 class="flex items-center gap-2 text-lg font-semibold text-foreground">
        <Settings2 class="h-5 w-5 text-primary" /> 设置
      </h1>
      <p class="mt-0.5 text-xs text-muted-foreground">
        系统配置与偏好
        <span v-if="version" class="ml-1 font-mono text-[10px]">v{{ version }}</span>
      </p>
    </div>

    <p v-if="loadError" class="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ loadError }}
    </p>

    <div class="flex flex-col gap-5 lg:flex-row lg:gap-6">
      <SettingsSidebar :active="active" @select="active = $event" />
      <main class="min-w-0 flex-1">
        <!-- 切换分区时重新挂载，保证各分区读取到最新的服务端配置 -->
        <component :is="current" :key="active" />
      </main>
    </div>
  </div>
</template>
