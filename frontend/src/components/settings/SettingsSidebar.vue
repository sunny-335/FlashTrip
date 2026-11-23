<script setup lang="ts">
/**
 * 设置页侧边导航：桌面竖排分组菜单（宽约 220px），手机 / 平板收成顶部横向可滚动标签。
 * 选中态为青绿左边框 + 浅底，不使用渐变；分组与图标在此内聚维护。
 */
import {
  Sun, Eye, Bot, MapPinned, CloudSun, Mail, ShieldCheck, Archive, HardDrive, Users,
} from 'lucide-vue-next'
import type { Component } from 'vue'

export interface SidebarItem {
  key: string
  label: string
  icon: Component
}
export interface SidebarGroup {
  label: string
  items: SidebarItem[]
}

defineProps<{ active: string }>()
const emit = defineEmits<{ select: [key: string] }>()

const groups: SidebarGroup[] = [
  {
    label: '个性化',
    items: [
      { key: 'appearance', label: '外观', icon: Sun },
      { key: 'moments', label: '瞬间默认可见性', icon: Eye },
      { key: 'people', label: '家庭与人员', icon: Users },
    ],
  },
  {
    label: '服务接入',
    items: [
      { key: 'ai', label: '人工智能', icon: Bot },
      { key: 'map', label: '地图', icon: MapPinned },
      { key: 'weather', label: '天气', icon: CloudSun },
      { key: 'mail', label: '邮件通知', icon: Mail },
    ],
  },
  {
    label: '账户与数据',
    items: [
      { key: 'storage', label: '对象存储', icon: HardDrive },
      { key: 'account', label: '账户与安全', icon: ShieldCheck },
      { key: 'backup', label: '备份', icon: Archive },
    ],
  },
]
const flatItems: SidebarItem[] = groups.flatMap((g) => g.items)
</script>

<template>
  <aside class="lg:w-[220px] lg:shrink-0">
    <!-- 桌面：竖排分组菜单常驻 -->
    <nav class="hidden lg:flex lg:flex-col gap-0.5">
      <div v-for="g in groups" :key="g.label" class="mb-3">
        <p class="mb-1 px-3 text-[11px] font-medium text-muted-foreground">{{ g.label }}</p>
        <button
          v-for="item in g.items"
          :key="item.key"
          type="button"
          class="flex w-full items-center gap-2 rounded-r-md border-l-2 py-2 pl-3 pr-2 text-left text-sm transition-colors"
          :class="active === item.key
            ? 'border-primary bg-accent font-medium text-accent-foreground'
            : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground'"
          @click="emit('select', item.key)"
        >
          <component :is="item.icon" class="h-4 w-4 shrink-0" />
          <span class="truncate">{{ item.label }}</span>
        </button>
      </div>
    </nav>

    <!-- 手机 / 平板：顶部横向可滚动标签 -->
    <div class="nav-scroll -mx-1 flex gap-1.5 px-1 pb-1 lg:hidden">
      <button
        v-for="item in flatItems"
        :key="item.key"
        type="button"
        class="shrink-0 whitespace-nowrap rounded-lg border px-3 py-1.5 text-xs transition-colors"
        :class="active === item.key
          ? 'border-primary bg-accent font-medium text-accent-foreground'
          : 'border-border bg-card text-muted-foreground hover:bg-muted'"
        @click="emit('select', item.key)"
      >
        {{ item.label }}
      </button>
    </div>
  </aside>
</template>
