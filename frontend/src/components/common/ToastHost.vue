<script setup lang="ts">
/** 全局顶部居中飘窗提示宿主：固定于视口顶部居中，自动消失，可手动关闭。 */
import { useToastStore } from '@/stores/toast'
import { CheckCircle2, Info, XCircle, X } from 'lucide-vue-next'

const store = useToastStore()

const icons = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
} as const
</script>

<template>
  <Teleport to="body">
    <div
      class="pointer-events-none fixed inset-x-0 top-4 z-[100] flex flex-col items-center gap-2 px-4"
      aria-live="polite"
    >
      <TransitionGroup
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="-translate-y-2 opacity-0"
        enter-to-class="translate-y-0 opacity-100"
        leave-active-class="transition duration-150 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-for="item in store.items"
          :key="item.id"
          class="pointer-events-auto flex w-full max-w-md items-start gap-2.5 rounded-lg border border-border bg-card px-4 py-3 shadow-lg shadow-black/5"
          role="status"
        >
          <component
            :is="icons[item.kind]"
            class="mt-0.5 size-4 shrink-0"
            :class="{
              'text-primary': item.kind === 'success',
              'text-destructive': item.kind === 'error',
              'text-muted-foreground': item.kind === 'info',
            }"
          />
          <p class="min-w-0 flex-1 text-sm leading-relaxed text-card-foreground">{{ item.message }}</p>
          <button
            type="button"
            class="shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
            aria-label="关闭提示"
            @click="store.dismiss(item.id)"
          >
            <X class="size-3.5" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
