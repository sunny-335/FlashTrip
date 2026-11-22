<script setup lang="ts">
/** 外观分区：浅色 / 深色 / 跟随系统三选一，调用 N3 的 useUiStore().setTheme。 */
import { computed } from 'vue'
import { Sun, Moon, Monitor } from 'lucide-vue-next'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import { useUiStore } from '@/stores/ui'
import { useMediaQuery } from '@/composables/useMediaQuery'

const ui = useUiStore()
const systemDark = useMediaQuery('(prefers-color-scheme: dark)')

const options = [
  { value: 'light' as const, label: '浅色', icon: Sun },
  { value: 'dark' as const, label: '深色', icon: Moon },
  { value: 'system' as const, label: '跟随系统', icon: Monitor },
]

const effective = computed(() => {
  if (ui.theme === 'system') return systemDark.value ? '深色' : '浅色'
  return ui.theme === 'dark' ? '深色' : '浅色'
})
const description = computed(() => (ui.theme === 'system'
  ? `当前跟随系统设置，实际生效为${effective.value}；系统主题变化时会自动切换。`
  : `当前固定为${effective.value}；该偏好仅保存在本机浏览器，不写入服务端配置。`))
</script>

<template>
  <Card class="space-y-3">
    <div>
      <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Sun class="h-4 w-4 text-primary" /> 外观
      </h2>
      <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
        选择界面主题。浅色与深色均采用暖白 / 深灰底色与青绿主色，切换后立即生效。
      </p>
    </div>

    <div class="flex flex-wrap gap-2">
      <Button
        v-for="o in options"
        :key="o.value"
        :variant="ui.theme === o.value ? 'default' : 'outline'"
        size="sm"
        @click="ui.setTheme(o.value)"
      >
        <component :is="o.icon" class="h-3.5 w-3.5" /> {{ o.label }}
      </Button>
    </div>

    <p class="rounded-md border border-border bg-muted/50 px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
      {{ description }}
    </p>
  </Card>
</template>
