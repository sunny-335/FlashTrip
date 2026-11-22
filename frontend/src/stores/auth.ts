/** 认证状态：user / login / logout / me / 邀请成员首次设密。字段对齐 UserOut。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/lib/api'

export interface User {
  id: string
  username: string
  email: string | null
  phone: string | null
  display_name: string
  avatar_url: string | null
  role: string
  is_active: boolean
  must_set_password: boolean
  password_set_at: string | null
  created_at: string | null
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)

  async function login(username: string, password: string): Promise<User> {
    loading.value = true
    try {
      const u = await api.post<User>('/auth/login', { username, password })
      user.value = u
      return u
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/auth/logout')
    } finally {
      user.value = null
    }
  }

  /** 读取当前会话；未登录返回 null（不抛错，供路由守卫/页面判定）。 */
  async function me(): Promise<User | null> {
    try {
      user.value = await api.get<User>('/auth/me')
      return user.value
    } catch {
      user.value = null
      return null
    }
  }

  /** 邀请成员首次设密（凭 setup 作用域 token 登录后调用）。 */
  async function setPassword(newPassword: string): Promise<User> {
    const u = await api.post<User>('/auth/set-password', { new_password: newPassword })
    user.value = u
    return u
  }

  return { user, loading, login, logout, me, setPassword }
})
