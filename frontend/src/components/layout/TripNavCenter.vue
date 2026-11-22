<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Check, Settings2 } from 'lucide-vue-next'
import { api } from '@/lib/api'

const route = useRoute()
const router = useRouter()
const tripId = computed(() => route.params.tripId as string)
const tabs = [
  { label: '行程', name: 'trip-plan' },
  { label: '预定', name: 'trip-bookings' },
  { label: '交通', name: 'trip-transports' },
  { label: '费用', name: 'trip-expenses' },
  { label: '物品', name: 'trip-packing' },
  { label: '瞬间', name: 'trip-moments' },
  { label: '协作', name: 'trip-collab' },
]
const settingCurrent = defineModel<boolean>('settingCurrent', { default: false })
const currentSet = defineModel<boolean>('currentSet', { default: false })

async function setCurrent() {
  settingCurrent.value = true
  try {
    await api.put(`/trips/${tripId.value}/current`)
    currentSet.value = true
    setTimeout(() => (currentSet.value = false), 2000)
  } catch {
    // 错误由全局提示处理
  } finally {
    settingCurrent.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex h-full max-w-[1600px] items-center px-5">
    <button class="flex w-40 shrink-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground" @click="router.push('/trips')">
      <ArrowLeft class="h-4 w-4" /> 返回
    </button>
    <nav class="mx-auto flex items-center gap-1">
      <RouterLink
        v-for="tab in tabs"
        :key="tab.name"
        :to="{ name: tab.name, params: { tripId } }"
        class="rounded-lg px-3.5 py-1.5 text-sm transition-colors"
        :class="route.name === tab.name
          ? 'bg-secondary font-medium text-foreground'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
      >{{ tab.label }}</RouterLink>
    </nav>
    <div class="flex w-40 shrink-0 justify-end">
      <button
        class="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-60"
        :disabled="settingCurrent"
        @click="setCurrent"
      >
        <Check v-if="currentSet" class="h-3.5 w-3.5 text-primary" />
        <Settings2 v-else class="h-3.5 w-3.5" />
        {{ currentSet ? '已设为当前' : '设置当前行程' }}
      </button>
    </div>
  </div>
</template>
