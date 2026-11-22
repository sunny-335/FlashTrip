/** 全局 UI 状态：主题、移动端断点、全局 Agent FAB 显隐。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Theme = 'light' | 'dark'
const LS_THEME = 'flashtrip.theme'

function readTheme(): Theme {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(LS_THEME) === 'dark'
      ? 'dark'
      : 'light'
  } catch {
    return 'light'
  }
}

function applyTheme(t: Theme): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', t === 'dark')
}

export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>(readTheme())
  // 不依赖组件生命周期：store 单例在初始化时注册一次 matchMedia 监听。
  const isMobile = ref(false)
  const showAgentFab = ref(true)

  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const mql = window.matchMedia('(max-width: 768px)')
    isMobile.value = mql.matches
    mql.addEventListener('change', (e) => {
      isMobile.value = e.matches
    })
  }

  function setTheme(t: Theme): void {
    theme.value = t
    applyTheme(t)
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(LS_THEME, t)
    } catch {
      /* 忽略 */
    }
  }

  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  function setIsMobile(v: boolean): void {
    isMobile.value = v
  }

  function setShowAgentFab(v: boolean): void {
    showAgentFab.value = v
  }

  applyTheme(theme.value)

  return { theme, isMobile, showAgentFab, setTheme, toggleTheme, setIsMobile, setShowAgentFab }
})
