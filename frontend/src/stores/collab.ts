/** 协作状态：成员 / 权限矩阵 / 邀请 + SSE 事件驱动的刷新。
 *  字段严格对齐 collab.py / invite_service.py：成员为 snake_case，邀请为 camelCase。
 */
import { defineStore } from 'pinia'
import { ref, watch, type WatchStopHandle } from 'vue'
import { api } from '@/lib/api'
import { useSSE, type SyncEvent, type UseSSEApi } from '@/composables/useSSE'

/** 与后端 deps.PERMISSION_KEYS 完全一致的 10 个权限点。 */
export const PERMISSION_KEYS = [
  'trip:read', 'plan:write', 'booking:write', 'transport:write', 'expense:write',
  'packing:write', 'moment:write', 'member:manage', 'trip:settings', 'ai:use',
] as const

export const PERMISSION_LABELS: Record<string, string> = {
  'trip:read': '查看行程',
  'plan:write': '编辑行程安排',
  'booking:write': '编辑预订',
  'transport:write': '编辑交通',
  'expense:write': '编辑费用',
  'packing:write': '编辑物品',
  'moment:write': '编辑瞬间',
  'member:manage': '管理成员',
  'trip:settings': '行程设置',
  'ai:use': '使用智能助手',
}

/** 默认只读权限。 */
export const DEFAULT_PERMISSION_KEYS = ['trip:read']

export interface MemberUser {
  id: string
  username?: string
  display_name?: string
  email?: string | null
  phone?: string | null
  role?: string
}

export interface Member {
  id: string
  trip_id?: string
  user_id?: string
  role?: string
  joined_at?: string | null
  user?: MemberUser
  /** 邀请时填写的昵称 / 邮箱，有则随成员返回。 */
  nickname?: string | null
  email?: string | null
  permissions: Record<string, boolean>
}

/** 对齐 invite_service._dump 的 camelCase 输出。 */
export interface Invitation {
  id: string
  tripId: string
  channel: string
  targetValue: string
  permissionKeys: string[]
  expiresAt: string
  maxUses: number
  usedCount: number
  revokedAt: string | null
  createdBy: string | null
  createdAt: string
  /** 强制重置密码 / 受邀人昵称 / 邮箱。 */
  forceReset?: boolean
  nickname?: string | null
  email?: string | null
}

export interface CreateInviteResult {
  invitation: Invitation
  token: string
  inviteUrl: string
}

export interface CreateInviteIn {
  channel: 'phone' | 'email' | 'username'
  target_value: string
  permission_keys: string[]
  expires_days?: number
  max_uses?: number
  force_reset?: boolean
  nickname?: string
  email?: string
}

/** 分享链接：字段对齐 share_service._share_dict，创建时额外带 token / url。 */
export interface ShareLink {
  id: string
  trip_id: string
  title: string
  include_transports: boolean
  include_bookings: boolean
  include_packing: boolean
  include_expenses: boolean
  include_moments: boolean
  expires_at: string
  revoked_at: string | null
  created_by: string | null
  view_count: number
  created_at: string
  token?: string
  url?: string
}

export const useCollabStore = defineStore('collab', () => {
  const tripId = ref('')
  const members = ref<Member[]>([])
  const invites = ref<Invitation[]>([])
  const loading = ref(false)
  const error = ref('')
  const lastEvent = ref<SyncEvent | null>(null)

  // SSE 状态（由 useSSE 暴露的 ref 直接透出）
  const connected = ref(false)
  const mode = ref<'sse' | 'poll' | 'off'>('off')
  const syncError = ref('')

  let sse: UseSSEApi | null = null
  let refreshTimer: number | null = null
  let stopBridge: WatchStopHandle | null = null

  function base(): string {
    return `/trips/${encodeURIComponent(tripId.value)}`
  }

  async function load(id?: string): Promise<void> {
    if (id) tripId.value = id
    if (!tripId.value) return
    loading.value = true
    error.value = ''
    try {
      const [m, i] = await Promise.all([
        api.get<Member[]>(`${base()}/members`).catch(() => [] as Member[]),
        api.get<Invitation[]>(`${base()}/invites`).catch(() => [] as Invitation[]),
      ])
      members.value = (m ?? []).map((x) => ({ ...x, permissions: x.permissions ?? {} }))
      invites.value = i ?? []
    } catch (e) {
      error.value = (e as Error)?.message || '协作数据加载失败'
    } finally {
      loading.value = false
    }
  }

  /** 权限矩阵保存：后端接受 {permissions: {key: bool}}，返回 {memberId, permissions}。 */
  async function updatePermissions(memberId: string, permissions: Record<string, boolean>): Promise<void> {
    error.value = ''
    const res = await api.put<{ memberId: string; permissions: Record<string, boolean> }>(
      `${base()}/members/${encodeURIComponent(memberId)}/permissions`,
      { permissions },
    )
    const idx = members.value.findIndex((m) => m.id === memberId)
    if (idx >= 0) members.value[idx] = { ...members.value[idx], permissions: res.permissions ?? {} }
  }

  async function removeMember(memberId: string): Promise<void> {
    await api.del(`${base()}/members/${encodeURIComponent(memberId)}`)
    members.value = members.value.filter((m) => m.id !== memberId)
  }

  /** 创建邀请：返回一次性明文 token / inviteUrl，交由 InviteDialog 展示。 */
  async function createInvite(payload: CreateInviteIn): Promise<CreateInviteResult> {
    const result = await api.post<CreateInviteResult>(`${base()}/invites`, {
      channel: payload.channel,
      target_value: payload.target_value,
      permission_keys: payload.permission_keys,
      expires_days: payload.expires_days ?? 7,
      max_uses: payload.max_uses ?? 1,
      force_reset: Boolean(payload.force_reset),
      nickname: payload.nickname?.trim() || undefined,
      email: payload.email?.trim() || undefined,
    })
    invites.value = [result.invitation, ...invites.value]
    return result
  }

  async function revokeInvite(inviteId: string): Promise<void> {
    await api.del(`${base()}/invites/${encodeURIComponent(inviteId)}`)
    invites.value = invites.value.filter((i) => i.id !== inviteId)
  }

  /** 事件到达后合并 250ms 内的多次刷新，避免 SSE 突发导致请求风暴。 */
  function scheduleRefresh(): void {
    if (refreshTimer !== null) window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null
      void load()
    }, 250)
  }

  function onSyncEvent(ev: SyncEvent): void {
    lastEvent.value = ev
    scheduleRefresh()
  }

  function connect(id?: string): void {
    if (id) tripId.value = id
    if (!tripId.value || sse) return
    sse = useSSE(() => tripId.value, { onEvent: onSyncEvent })
    // useSSE 在 store 内不会自动 unmount，用 watch 把其状态桥接到 store 的 ref
    stopBridge = watch(
      [sse.connected, sse.mode, sse.error],
      ([c, m, e]) => {
        connected.value = c
        mode.value = m
        syncError.value = e
      },
      { immediate: true },
    )
    sse.start()
  }

  function disconnect(): void {
    stopBridge?.()
    stopBridge = null
    sse?.stop()
    sse = null
    connected.value = false
    mode.value = 'off'
    if (refreshTimer !== null) {
      window.clearTimeout(refreshTimer)
      refreshTimer = null
    }
  }

  return {
    tripId, members, invites, loading, error, lastEvent,
    connected, mode, syncError,
    load, updatePermissions, removeMember, createInvite, revokeInvite,
    connect, disconnect,
  }
})
