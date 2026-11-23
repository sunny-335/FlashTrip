<script setup lang="ts">
/** 瞬间默认可见性：全局默认开关，写入 PUT /settings 的用户偏好。 */
import { onMounted, ref } from 'vue'
import { Eye, Save, Loader2 } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'

const enabled = ref(false)
const loading = ref(true)
const saving = ref(false)
const toast = useToastStore()

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}

async function load() {
  loading.value = true
  try {
    const s = await api.get<{ moment_default_public?: boolean }>('/settings')
    enabled.value = Boolean(s.moment_default_public)
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    await api.put('/settings', { moment_default_public: enabled.value })
    toast.success('默认可见性已保存')
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <Card class="space-y-3">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Eye class="h-4 w-4 text-primary" /> 瞬间默认可见性
        </h2>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
          控制新建旅途瞬间的全局默认值。逐条瞬间仍可单独设置是否对外展示。
        </p>
      </div>
      <Button size="sm" :disabled="saving || loading" @click="save">
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        <Save v-else class="h-3.5 w-3.5" /> 保存
      </Button>
    </div>

    <label class="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-sm text-foreground">
      <input v-model="enabled" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
      新瞬间默认对外展示
    </label>
    <p class="text-[11px] leading-relaxed text-muted-foreground">
      关闭时新建瞬间默认仅自己可见。每条行程的分享链接、成员与权限请在行程协作页单独管理。
    </p>

    <p v-if="loading" class="text-xs text-muted-foreground">正在读取偏好…</p>
  </Card>
</template>
