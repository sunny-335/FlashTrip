/** 响应式媒体查询；SSR / 测试环境安全。 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useMediaQuery(query: string): Ref<boolean> {
  const matches = ref(false)
  let mql: MediaQueryList | null = null

  const update = () => {
    if (mql) matches.value = mql.matches
  }

  onMounted(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    mql = window.matchMedia(query)
    matches.value = mql.matches
    mql.addEventListener('change', update)
  })

  onBeforeUnmount(() => {
    mql?.removeEventListener('change', update)
  })

  return matches
}

/** 移动端断点（≤768px）：禁用 Sortable，改渲染上下/移至某天按钮。 */
export function useIsMobile(): Ref<boolean> {
  return useMediaQuery('(max-width: 768px)')
}
