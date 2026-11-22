<script setup lang="ts">
/** 协作页：人数摘要 + 成员 + 权限矩阵 + 邀请 + 分享链接；SSE 事件到达后由 collab store 自动刷新。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Users, Link2, Radio, RefreshCw, Trash2, Loader2, Save, Plus, Share2, Copy, Check, UsersRound,
} from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import MemberList from '@/components/collab/MemberList.vue'
import PermissionMatrix from '@/components/collab/PermissionMatrix.vue'
import InviteDialog from '@/components/collab/InviteDialog.vue'
import ShareDialog from '@/components/collab/ShareDialog.vue'
import { useAuthStore } from '@/stores/auth'
import {
  useCollabStore, PERMISSION_KEYS, type Invitation, type Member, type ShareLink,
} from '@/stores/collab'

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const collab = useCollabStore()
const auth = useAuthStore()

const selectedId = ref<string | null>(null)
const draft = ref<Record<string, boolean>>({})
const inviteOpen = ref(false)
const shareOpen = ref(false)
const revokeTarget = ref<Invitation | null>(null)
const removeTarget = ref<Member | null>(null)
const saving = ref(false)
const busy = ref(false)
const localError = ref('')
const notice = ref('')

// ---------------------------------------------------------------- 人数摘要
interface TripPeople {
  traveler_count?: number
  has_children?: boolean
  children_count?: number
  family_mode?: boolean
  family_name?: string | null
}
const tripPeople = ref<TripPeople | null>(null)
const peopleSummary = computed(() => {
  const t = tripPeople.value
  if (!t) return ''
  const total = Number(t.traveler_count) || 1
  const parts = [`${total} 人参加`]
  if (t.has_children && Number(t.children_count) > 0) parts.push(`含 ${t.children_count} 名儿童`)
  if (t.family_mode) parts.push(t.family_name ? `家庭模式：${t.family_name}` : '家庭模式')
  return parts.join(' · ')
})

// ---------------------------------------------------------------- 分享链接
const shares = ref<ShareLink[]>([])
const sharesLoading = ref(false)
const shareRevokeTarget = ref<ShareLink | null>(null)
const copiedShare = ref('')

async function loadShares() {
  sharesLoading.value = true
  try {
    shares.value = await api.get<ShareLink[]>(`/trips/${encodeURIComponent(tripId.value)}/shares`)
  } catch (e) {
    localError.value = e instanceof ApiError ? e.message : (e as Error)?.message || '分享链接加载失败'
  } finally {
    sharesLoading.value = false
  }
}
function shareFullLink(s: ShareLink): string {
  if (s.url) return `${window.location.origin}${s.url.startsWith('/') ? s.url : `/${s.url}`}`
  return '' // 历史列表不含明文令牌，仅新创建时展示一次
}
async function copyShareLink(s: ShareLink) {
  const link = shareFullLink(s)
  if (!link) return
  try {
    await navigator.clipboard.writeText(link)
    copiedShare.value = s.id
    window.setTimeout(() => { copiedShare.value = '' }, 1800)
  } catch {
    // 剪贴板不可用时忽略
  }
}
async function confirmRevokeShare() {
  if (!shareRevokeTarget.value) return
  busy.value = true
  localError.value = ''
  try {
    await api.del(`/trips/${encodeURIComponent(tripId.value)}/shares/${encodeURIComponent(shareRevokeTarget.value.id)}`)
    await loadShares()
  } catch (e) {
    localError.value = e instanceof ApiError ? e.message : (e as Error)?.message || '撤销失败'
  } finally {
    busy.value = false
    shareRevokeTarget.value = null
  }
}

const myId = computed(() => auth.user?.id ?? '')
const canManage = computed(() => {
  const role = auth.user?.role
  if (role === 'owner' || role === 'admin') return true
  const me = collab.members.find((m) => m.user_id === myId.value || m.user?.id === myId.value)
  return Boolean(me?.permissions?.['member:manage'])
})

const selected = computed<Member | null>(
  () => collab.members.find((m) => m.id === selectedId.value) ?? null,
)

function fullPermissions(source: Record<string, boolean> | undefined): Record<string, boolean> {
  return Object.fromEntries(PERMISSION_KEYS.map((k) => [k, Boolean(source?.[k])]))
}

function selectMember(id: string) {
  selectedId.value = id
  const m = collab.members.find((x) => x.id === id)
  draft.value = fullPermissions(m?.permissions)
  localError.value = ''
}

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}

async function savePermissions() {
  if (!selectedId.value || !canManage.value) return
  saving.value = true
  localError.value = ''
  try {
    await collab.updatePermissions(selectedId.value, draft.value)
    notice.value = '权限已保存'
    window.setTimeout(() => { notice.value = '' }, 2000)
  } catch (e) {
    localError.value = messageOf(e)
  } finally {
    saving.value = false
  }
}

async function confirmRevoke() {
  if (!revokeTarget.value) return
  busy.value = true
  localError.value = ''
  try {
    await collab.revokeInvite(revokeTarget.value.id)
  } catch (e) {
    localError.value = messageOf(e)
  } finally {
    busy.value = false
    revokeTarget.value = null
  }
}

async function confirmRemove() {
  if (!removeTarget.value) return
  busy.value = true
  localError.value = ''
  try {
    await collab.removeMember(removeTarget.value.id)
    if (selectedId.value === removeTarget.value.id) selectedId.value = null
  } catch (e) {
    localError.value = messageOf(e)
  } finally {
    busy.value = false
    removeTarget.value = null
  }
}

// SSE 刷新后保持当前选中项的草稿与服务端一致（仅在未处于保存中时）
watch(() => collab.lastEvent, (ev) => {
  if (!ev || saving.value || !selectedId.value) return
  const m = collab.members.find((x) => x.id === selectedId.value)
  if (m) draft.value = fullPermissions(m.permissions)
})

onMounted(async () => {
  await Promise.all([auth.me(), collab.load(tripId.value)])
  collab.connect(tripId.value)
  // 人数摘要与分享链接独立加载，失败不影响主流程
  api.get<TripPeople>(`/trips/${encodeURIComponent(tripId.value)}`)
    .then((t) => { tripPeople.value = t })
    .catch(() => { tripPeople.value = null })
  void loadShares()
})
onBeforeUnmount(() => collab.disconnect())
</script>

<template>
  <div class="mx-auto max-w-[1100px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Users class="h-5 w-5 text-primary" /> 协作</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">成员权限、邀请与分享链接，变更通过实时同步推送</p>
      </div>
      <div class="flex items-center gap-2">
        <span class="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground">
          <Radio class="h-3 w-3" :class="collab.connected ? 'text-primary' : 'text-muted-foreground'" />
          {{ collab.connected ? '实时同步已连接' : collab.mode === 'poll' ? '轮询同步中' : '未连接' }}
        </span>
        <Button variant="outline" size="sm" @click="collab.load()"><RefreshCw class="h-3.5 w-3.5" /> 刷新</Button>
        <Button variant="outline" size="sm" :disabled="!canManage" @click="shareOpen = true"><Share2 class="h-3.5 w-3.5" /> 新建分享链接</Button>
        <Button size="sm" :disabled="!canManage" @click="inviteOpen = true"><Plus class="h-3.5 w-3.5" /> 新建邀请</Button>
      </div>
    </div>

    <!-- 人数 / 儿童 / 家庭摘要 -->
    <div v-if="peopleSummary" class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-foreground">
      <UsersRound class="h-3.5 w-3.5 text-primary" />
      <span>{{ peopleSummary }}</span>
      <span class="text-muted-foreground">可在行程编辑里调整参加人数</span>
    </div>

    <p v-if="collab.error || localError || collab.syncError" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ collab.error || localError || collab.syncError }}
    </p>
    <p v-if="notice" class="rounded-lg border border-primary/40 bg-accent/50 p-2.5 text-xs text-foreground">{{ notice }}</p>

    <div v-if="collab.loading" class="py-10 text-center text-sm text-muted-foreground">
      <Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在加载协作数据…
    </div>

    <template v-else>
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <!-- 成员列表 -->
        <Card>
          <h2 class="mb-3 text-sm font-semibold">成员 <span class="text-muted-foreground">({{ collab.members.length }})</span></h2>
          <MemberList
            :members="collab.members"
            :selected-id="selectedId"
            :can-manage="canManage"
            @select="selectMember"
            @remove="removeTarget = $event"
          />
          <p class="mt-3 text-[11px] text-muted-foreground">选中成员后在右侧编辑权限；所有者不可移除。</p>
        </Card>

        <!-- 权限矩阵 -->
        <Card>
          <template v-if="selected">
            <div class="mb-3 flex items-center justify-between">
              <h2 class="text-sm font-semibold">编辑权限</h2>
              <Badge variant="outline">{{ selected.nickname || selected.user?.display_name || selected.user?.username || '成员' }}</Badge>
            </div>
            <PermissionMatrix v-model="draft" :disabled="!canManage" />
            <Button class="mt-3" size="sm" :disabled="!canManage || saving" @click="savePermissions">
              <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
              <Save v-else class="h-3.5 w-3.5" /> 保存权限
            </Button>
          </template>
          <div v-else class="grid min-h-[220px] place-items-center text-center">
            <p class="text-xs text-muted-foreground">从左侧选择一位成员以编辑其权限矩阵。</p>
          </div>
        </Card>
      </div>

      <!-- 邀请列表 -->
      <Card>
        <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Link2 class="h-4 w-4 text-primary" /> 邀请链接
          <span class="text-muted-foreground">({{ collab.invites.length }})</span>
        </h2>
        <div v-if="!collab.invites.length" class="rounded-lg border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
          还没有邀请链接，点「新建邀请」创建。
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-border text-muted-foreground">
              <tr>
                <th class="py-2 pr-3 font-medium">渠道 / 目标</th>
                <th class="py-2 pr-3 font-medium">受邀人</th>
                <th class="py-2 pr-3 font-medium">权限</th>
                <th class="py-2 pr-3 font-medium">有效期</th>
                <th class="py-2 pr-3 font-medium">使用</th>
                <th class="py-2 pr-3 font-medium">状态</th>
                <th class="py-2 font-medium" />
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr v-for="inv in collab.invites" :key="inv.id">
                <td class="py-2 pr-3">
                  <span class="block font-medium text-foreground">{{ inv.targetValue }}</span>
                  <span class="text-[10px] text-muted-foreground">{{ inv.channel }}</span>
                </td>
                <td class="py-2 pr-3 text-muted-foreground">
                  <span v-if="inv.nickname || inv.email" class="block">{{ inv.nickname || inv.email }}</span>
                  <span v-if="inv.forceReset" class="text-[10px] text-primary">需重置密码</span>
                  <span v-else-if="!inv.nickname && !inv.email">—</span>
                </td>
                <td class="py-2 pr-3 text-muted-foreground">{{ inv.permissionKeys.length }} 项</td>
                <td class="py-2 pr-3 text-muted-foreground">{{ formatDate(inv.expiresAt) }}</td>
                <td class="py-2 pr-3 text-muted-foreground">{{ inv.usedCount }} / {{ inv.maxUses }}</td>
                <td class="py-2 pr-3">
                  <Badge v-if="inv.revokedAt" variant="destructive">已撤销</Badge>
                  <Badge v-else-if="inv.usedCount >= inv.maxUses" variant="secondary">已用尽</Badge>
                  <Badge v-else variant="default">有效</Badge>
                </td>
                <td class="py-2 text-right">
                  <Button
                    v-if="canManage && !inv.revokedAt"
                    variant="ghost"
                    size="sm"
                    class="text-destructive hover:bg-destructive/10 hover:text-destructive"
                    @click="revokeTarget = inv"
                  ><Trash2 class="h-3.5 w-3.5" /> 撤销</Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <!-- 分享链接列表 -->
      <Card>
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="flex items-center gap-2 text-sm font-semibold">
            <Share2 class="h-4 w-4 text-primary" /> 分享链接
            <span class="text-muted-foreground">({{ shares.length }})</span>
          </h2>
          <div class="flex items-center gap-2">
            <Button variant="outline" size="sm" @click="loadShares"><RefreshCw class="h-3.5 w-3.5" /> 刷新</Button>
            <Button size="sm" :disabled="!canManage" @click="shareOpen = true"><Plus class="h-3.5 w-3.5" /> 新建分享链接</Button>
          </div>
        </div>
        <div v-if="sharesLoading" class="py-6 text-center text-xs text-muted-foreground"><Loader2 class="mx-auto mb-1.5 h-4 w-4 animate-spin" /> 正在加载…</div>
        <div v-else-if="!shares.length" class="rounded-lg border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
          还没有分享链接。生成一条公开只读链接，把行程概览发给家人朋友。
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-border text-muted-foreground">
              <tr>
                <th class="py-2 pr-3 font-medium">标题</th>
                <th class="py-2 pr-3 font-medium">包含内容</th>
                <th class="py-2 pr-3 font-medium">有效期至</th>
                <th class="py-2 pr-3 font-medium">浏览</th>
                <th class="py-2 pr-3 font-medium">状态</th>
                <th class="py-2 font-medium" />
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr v-for="s in shares" :key="s.id">
                <td class="py-2 pr-3 font-medium text-foreground">{{ s.title || '未命名分享' }}</td>
                <td class="py-2 pr-3">
                  <div class="flex flex-wrap gap-1">
                    <Badge v-if="s.include_transports" variant="outline">交通</Badge>
                    <Badge v-if="s.include_bookings" variant="outline">预订</Badge>
                    <Badge v-if="s.include_packing" variant="outline">物品</Badge>
                    <Badge v-if="s.include_expenses" variant="outline">费用</Badge>
                    <Badge v-if="s.include_moments" variant="outline">瞬间</Badge>
                    <span v-if="!s.include_transports && !s.include_bookings && !s.include_packing && !s.include_expenses && !s.include_moments" class="text-muted-foreground">仅行程信息</span>
                  </div>
                </td>
                <td class="py-2 pr-3 text-muted-foreground">{{ formatDate(s.expires_at) }}</td>
                <td class="py-2 pr-3 text-muted-foreground">{{ s.view_count }} 次</td>
                <td class="py-2 pr-3">
                  <Badge v-if="s.revoked_at" variant="destructive">已撤销</Badge>
                  <Badge v-else variant="default">有效</Badge>
                </td>
                <td class="py-2">
                  <div class="flex flex-wrap justify-end gap-1.5">
                    <Button v-if="!s.revoked_at && s.url" variant="outline" size="sm" @click="copyShareLink(s)">
                      <Check v-if="copiedShare === s.id" class="h-3.5 w-3.5" /> <Copy v-else class="h-3.5 w-3.5" />
                      {{ copiedShare === s.id ? '已复制' : '复制链接' }}
                    </Button>
                    <Button
                      v-if="canManage && !s.revoked_at"
                      variant="ghost"
                      size="sm"
                      class="text-destructive hover:bg-destructive/10 hover:text-destructive"
                      @click="shareRevokeTarget = s"
                    ><Trash2 class="h-3.5 w-3.5" /> 撤销</Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          历史链接不含一次性明文令牌，无法再次复制完整地址；如需重新分享，请新建一条链接。
        </p>
      </Card>
    </template>

    <InviteDialog v-model="inviteOpen" :trip-id="tripId" @created="collab.load()" />
    <ShareDialog v-model="shareOpen" :trip-id="tripId" @created="loadShares" />
    <ConfirmDialog
      :model-value="!!revokeTarget"
      title="撤销邀请"
      message="撤销后该链接立即失效，确定继续吗？"
      confirm-text="撤销"
      danger
      :busy="busy"
      @update:model-value="(v) => { if (!v) revokeTarget = null }"
      @confirm="confirmRevoke"
    />
    <ConfirmDialog
      :model-value="!!removeTarget"
      title="移除成员"
      :message="`确定移除该成员吗？其权限记录将一并失效。`"
      confirm-text="移除"
      danger
      :busy="busy"
      @update:model-value="(v) => { if (!v) removeTarget = null }"
      @confirm="confirmRemove"
    />
    <ConfirmDialog
      :model-value="!!shareRevokeTarget"
      title="撤销分享链接"
      message="撤销后该公开链接立即失效，确定继续吗？"
      confirm-text="撤销"
      danger
      :busy="busy"
      @update:model-value="(v) => { if (!v) shareRevokeTarget = null }"
      @confirm="confirmRevokeShare"
    />
  </div>
</template>
