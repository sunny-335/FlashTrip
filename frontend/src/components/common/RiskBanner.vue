<script setup lang="ts">
import { ref } from 'vue'
import { AlertTriangle, X } from 'lucide-vue-next'

const dismissed = ref(localStorage.getItem('flashtrip-risk-dismissed') === '1')
function dismiss() {
  dismissed.value = true
  localStorage.setItem('flashtrip-risk-dismissed', '1')
}
</script>

<template>
  <div v-if="!dismissed" class="fixed bottom-3 left-1/2 z-20 flex max-w-2xl -translate-x-1/2 items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shadow-sm">
    <AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
    <span>境外底图（OpenFreeMap / OSM / Mapbox）无中国审图号，仅建议用于境外行程或个人自用；境内公开服务请配置合规底图、审图号与 ICP 备案。</span>
    <button class="ml-1 shrink-0 hover:text-amber-950" @click="dismiss"><X class="h-3.5 w-3.5" /></button>
  </div>
</template>
