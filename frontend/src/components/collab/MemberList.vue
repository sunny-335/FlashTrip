<script setup lang="ts">
/** 成员列表：展示成员身份 + 权限摘要，可选中编辑 / 移除（owner 不可移除）。 */
import { UserRound, ShieldCheck, Trash2 } from 'lucide-vue-next'
import type { Member } from '@/stores/collab'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/common/EmptyState.vue'

defineProps<{
  members: Member[]
  selectedId?: string | null
  canManage?: boolean
}>()
const emit = defineEmits<{ select: [id: string]; remove: [id: string] }>()

function displayName(m: Member): string {
  return m.user?.display_name || m.user?.username || m.user?.email || m.user?.phone || m.user_id || '未知成员'
}
function granted(m: Member): number {
  return Object.values(m.permissions ?? {}).filter(Boolean).length
}
function isOwner(m: Member): boolean {
  return m.role === 'owner' || m.role === 'admin' || m.user?.role === 'owner' || m.user?.role === 'admin'
}
</script>

<template>
  <div class="space-y-2">
    <EmptyState v-if="!members.length" title="还没有成员" description="通过邀请链接添加协作者。" :icon="UserRound" />
    <button
      v-for="m in members"
      :key="m.id"
      class="flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors"
      :class="selectedId === m.id
        ? 'border-primary/60 bg-accent'
        : 'border-border bg-card hover:bg-muted'"
      @click="emit('select', m.id)"
    >
      <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <UserRound class="h-4 w-4" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-xs font-medium text-foreground">{{ displayName(m) }}</span>
        <span class="block truncate text-[10px] text-muted-foreground">
          {{ m.user?.username ? `@${m.user.username} · ` : '' }}{{ granted(m) }} 项权限
        </span>
      </span>
      <Badge v-if="isOwner(m)" variant="default"><ShieldCheck class="mr-0.5 inline h-2.5 w-2.5" />所有者</Badge>
      <Badge v-else variant="secondary">{{ m.role || 'member' }}</Badge>
      <Button
        v-if="canManage && !isOwner(m)"
        variant="ghost"
        size="sm"
        class="h-7 w-7 shrink-0 p-0 text-muted-foreground hover:text-destructive"
        title="移除成员"
        @click.stop="emit('remove', m.id)"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </Button>
    </button>
  </div>
</template>
