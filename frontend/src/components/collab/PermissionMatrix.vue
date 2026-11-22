<script setup lang="ts">
/** 权限矩阵：10 个权限点的开关，默认只读 trip:read；v-model 为 Record<key, boolean>。 */
import { computed } from 'vue'
import { LockKeyhole } from 'lucide-vue-next'
import { PERMISSION_KEYS, PERMISSION_LABELS, DEFAULT_PERMISSION_KEYS } from '@/stores/collab'
import Badge from '@/components/ui/Badge.vue'

const props = withDefaults(
  defineProps<{ disabled?: boolean }>(),
  { disabled: false },
)
const model = defineModel<Record<string, boolean>>({ default: () => ({}) })

const rows = computed(() =>
  PERMISSION_KEYS.map((key) => ({ key, label: PERMISSION_LABELS[key] ?? key })),
)
const grantedCount = computed(() => rows.value.filter((r) => model.value[r.key]).length)

function toggle(key: string) {
  if (props.disabled) return
  model.value = { ...model.value, [key]: !model.value[key] }
}

function resetReadonly() {
  if (props.disabled) return
  const next: Record<string, boolean> = {}
  for (const k of PERMISSION_KEYS) next[k] = DEFAULT_PERMISSION_KEYS.includes(k)
  model.value = next
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-1.5 text-xs font-medium">
        <LockKeyhole class="h-3.5 w-3.5 text-primary" /> 权限矩阵
        <Badge variant="outline">{{ grantedCount }} / {{ rows.length }}</Badge>
      </div>
      <button
        class="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
        :disabled="disabled"
        @click="resetReadonly"
      >重置为只读</button>
    </div>
    <div class="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
      <label
        v-for="r in rows"
        :key="r.key"
        class="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs"
        :class="disabled ? 'cursor-default opacity-70' : 'cursor-pointer hover:bg-muted'"
      >
        <span class="min-w-0">
          <span class="block truncate text-foreground">{{ r.label }}</span>
          <span class="block truncate font-mono text-[10px] text-muted-foreground">{{ r.key }}</span>
        </span>
        <input
          type="checkbox"
          class="h-3.5 w-3.5 shrink-0 accent-[var(--primary)]"
          :checked="!!model[r.key]"
          :disabled="disabled"
          @change="toggle(r.key)"
        />
      </label>
    </div>
    <p class="text-[10px] leading-relaxed text-muted-foreground">
      默认只读成员仅拥有 trip:read；任何写操作在后端按同一套权限校验，缺失时返回 403。
    </p>
  </div>
</template>
