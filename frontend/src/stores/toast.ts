/** 全局顶部居中飘窗提示：统一替代页面内散落的内联提示条。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  kind: ToastKind
  message: string
  duration: number
}

let nextId = 1

/** 相同文案在展示期间去重，避免批量操作时刷屏。 */
function dedupe(items: ToastItem[], message: string): boolean {
  return items.some((item) => item.message === message)
}

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])

  function push(kind: ToastKind, message: string, duration = 3200): number {
    if (dedupe(items.value, message)) return -1
    const id = nextId++
    items.value.push({ id, kind, message, duration })
    if (duration > 0) {
      setTimeout(() => dismiss(id), duration)
    }
    return id
  }

  function dismiss(id: number): void {
    const index = items.value.findIndex((item) => item.id === id)
    if (index >= 0) items.value.splice(index, 1)
  }

  function success(message: string, duration?: number): number {
    return push('success', message, duration)
  }

  function error(message: string, duration = 5000): number {
    return push('error', message, duration)
  }

  function info(message: string, duration?: number): number {
    return push('info', message, duration)
  }

  return { items, push, dismiss, success, error, info }
})

/** 便捷调用：在非组件上下文（如 lib/api.ts）直接使用。 */
export const toast = {
  success: (message: string, duration?: number) => useToastStore().success(message, duration),
  error: (message: string, duration?: number) => useToastStore().error(message, duration),
  info: (message: string, duration?: number) => useToastStore().info(message, duration),
}
