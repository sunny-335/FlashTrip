/** 全局 UI 状态：主题（浅色 / 深色 / 跟随系统）、三端断点、全局 Agent 悬浮按钮显隐。 */
import { defineStore } from 'pinia'
import { ref, type Ref } from 'vue'

export type Theme = 'light' | 'dark' | 'system'
const LS_THEME = 'flashtrip.theme'

/** 兼容旧值：旧版仅存 light / dark，其余（含缺省）按跟随系统处理。 */
function normalizeTheme(value: unknown): Theme {
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

function readTheme(): Theme {
  try {
    return typeof localStorage !== 'undefined'
      ? normalizeTheme(localStorage.getItem(LS_THEME))
      : 'system'
  } catch {
    return 'system'
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** 把主题解析为是否启用深色：system 取系统偏好，旧值 light / dark 直接生效。 */
function resolveDark(theme: Theme): boolean {
  return theme === 'system' ? systemPrefersDark() : theme === 'dark'
}

/** 应用主题到根元素；system 时按系统当前值切换 .dark。 */
function applyThemeClass(theme: Theme): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', resolveDark(theme))
}

/** 三端断点：手机 ≤768、平板 769–1024、桌面 >1024。 */
const MEDIA = {
  mobile: '(max-width: 768px)',
  tablet: '(min-width: 769px) and (max-width: 1024px)',
  desktop: '(min-width: 1025px)',
} as const

/** 在 store 单例内注册一次媒体查询监听，不依赖组件生命周期。 */
function bindMedia(query: string, target: Ref<boolean>): void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  const mql = window.matchMedia(query)
  target.value = mql.matches
  mql.addEventListener('change', (event) => {
    target.value = event.matches
  })
}

export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>(readTheme())
  const isMobile = ref(false)
  const isTablet = ref(false)
  const isDesktop = ref(false)
  const showAgentFab = ref(true)

  bindMedia(MEDIA.mobile, isMobile)
  bindMedia(MEDIA.tablet, isTablet)
  bindMedia(MEDIA.desktop, isDesktop)

  // 跟随系统：系统深浅变化时实时重放，仅 system 模式生效
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const systemMql = window.matchMedia('(prefers-color-scheme: dark)')
    systemMql.addEventListener('change', () => {
      if (theme.value === 'system') applyThemeClass('system')
    })
  }

  /** 设置主题，支持 light / dark / system，并写入本地偏好。 */
  function setTheme(next: Theme): void {
    theme.value = normalizeTheme(next)
    applyThemeClass(theme.value)
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(LS_THEME, theme.value)
    } catch {
      /* 隐私模式下忽略 */
    }
  }

  /** 与旧版一致在浅色 / 深色间切换；system 时按当前生效深浅取反。 */
  function toggleTheme(): void {
    setTheme(resolveDark(theme.value) ? 'light' : 'dark')
  }

  /** 重新应用当前主题，兼容旧值。 */
  function applyTheme(): void {
    applyThemeClass(normalizeTheme(theme.value))
  }

  function setIsMobile(value: boolean): void {
    isMobile.value = value
  }

  function setShowAgentFab(value: boolean): void {
    showAgentFab.value = value
  }

  applyTheme()

  return {
    theme, isMobile, isTablet, isDesktop, showAgentFab,
    setTheme, toggleTheme, applyTheme, setIsMobile, setShowAgentFab,
  }
})
