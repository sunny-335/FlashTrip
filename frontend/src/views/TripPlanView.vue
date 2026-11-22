<script setup lang="ts">
/** 行程规划页：解析 tripId、取行程标题，主体交给三栏 PlanBoard。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/lib/api'
import PlanBoard from '@/components/plan/PlanBoard.vue'
import type { Trip } from '@/stores/trip'

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const trip = ref<Trip | null>(null)

onMounted(async () => {
  try {
    trip.value = await api.get<Trip>(`/trips/${tripId.value}`)
  } catch {
    // 标题获取失败不阻断看板：PlanBoard 会自行加载 /plan 并展示错误
  }
})
</script>

<template>
  <PlanBoard :trip-id="tripId" :title="trip?.title ?? ''" />
</template>
