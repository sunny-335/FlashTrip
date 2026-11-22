/** 响应式媒体查询；SSR / 测试环境安全。 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** 三端断点：手机 ≤768、平板 769–1024、桌面 >1024。 */
export const BREAKPOINTS = {
  mobile: '(max-width: 768px)',
  tablet: '(min-width: 769px) and (max-width: 1024px)',
  desktop: '(min-width: 1025px)',
} as const

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

/** 移动端断点（≤768px）：禁用拖拽排序，改用上下 / 移至某天按钮。 */
export function useIsMobile(): Ref<boolean> {
  return useMediaQuery(BREAKPOINTS.mobile)
}

/** 平板断点（769–1024px）。 */
export function useIsTablet(): Ref<boolean> {
  return useMediaQuery(BREAKPOINTS.tablet)
}

/** 桌面断点（>1024px）。 */
export function useIsDesktop(): Ref<boolean> {
  return useMediaQuery(BREAKPOINTS.desktop)
}

/** 一次拿到三端断点，供布局判断使用。 */
export function useBreakpoint(): { isMobile: Ref<boolean>; isTablet: Ref<boolean>; isDesktop: Ref<boolean> } {
  return {
    isMobile: useIsMobile(),
    isTablet: useIsTablet(),
    isDesktop: useIsDesktop(),
  }
}
