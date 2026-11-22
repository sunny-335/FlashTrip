<script setup lang="ts">
/** 简化版对话框：Teleport + 遮罩 + ESC/点击遮罩关闭，v-model 控制显隐。 */
import { onBeforeUnmount, watch } from 'vue'
import { X } from 'lucide-vue-next'

const open = defineModel<boolean>({ default: false })
withDefaults(
  defineProps<{ title?: string; description?: string; width?: string }>(),
  { title: '', description: '', width: 'max-w-md' },
)

function close() {
  open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) close()
}
watch(open, (v) => {
  if (typeof window === 'undefined') return
  if (v) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/40" @click="close" />
      <div :class="['relative w-full rounded-lg border border-border bg-card shadow-lg', width]" role="dialog" aria-modal="true">
        <div v-if="title || description" class="flex items-start justify-between gap-4 border-b border-border px-5 py-3">
          <div>
            <h2 v-if="title" class="text-sm font-semibold text-foreground">{{ title }}</h2>
            <p v-if="description" class="mt-0.5 text-xs text-muted-foreground">{{ description }}</p>
          </div>
          <button class="rounded-md p-1 text-muted-foreground hover:bg-muted" aria-label="关闭" @click="close">
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="max-h-[70vh] overflow-y-auto px-5 py-4">
          <slot />
        </div>
        <div v-if="$slots.footer" class="flex justify-end gap-2 border-t border-border px-5 py-3">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
