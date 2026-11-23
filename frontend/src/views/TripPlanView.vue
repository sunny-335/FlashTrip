<script setup lang="ts">
/** 行程规划页：解析 tripId、取行程标题，主体交给三栏 PlanBoard。
 *  快捷键只在本视图注册：Ctrl+S 保存 / Ctrl+Z 撤销最近一次可撤销的移动。
 *  路由离开 / 卸载时若有未提交变更，自动 flush() 等待全部写请求落库，避免「返回就没了」。
 */
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { api, ApiError } from '@/lib/api'
import PlanBoard from '@/components/plan/PlanBoard.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { usePlanStore } from '@/stores/plan'
import type { PlanType } from '@/stores/plan'
import type { Trip } from '@/stores/trip'

const route = useRoute()
const router = useRouter()
const tripId = computed(() => String(route.params.tripId ?? ''))
const trip = ref<Trip | null>(null)
const plan = usePlanStore()

/** 删除行程：工具条入口 → 「是 / 否」二次确认 → DELETE → 返回行程列表。 */
const deleteOpen = ref(false)
const deleting = ref(false)
const deleteError = ref('')
async function confirmDeleteTrip(): Promise<void> {
  if (!tripId.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await api.del(`/trips/${encodeURIComponent(tripId.value)}`)
    deleteOpen.value = false
    await router.push('/trips')
  } catch (e) {
    deleteError.value = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    deleting.value = false
  }
}

interface BoardApi {
  openAdd: (type: PlanType, dayId?: string | null) => void
  undoLast: () => Promise<void> | void
}
const board = ref<BoardApi | null>(null)

/** 轻提示挂在 body 上，脱离本组件生命周期：路由离开后「已保存」仍能短暂显示。 */
let toastEl: HTMLElement | null = null
let toastTimer: number | undefined
function showToast(text: string): void {
  if (typeof document === 'undefined') return
  if (!toastEl) {
    toastEl = document.createElement('div')
    toastEl.className = 'pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-foreground shadow-sm'
    document.body.appendChild(toastEl)
  }
  toastEl.textContent = text
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toastEl?.remove()
    toastEl = null
  }, 1800)
}

/** 立即保存：等待所有写请求落库并清除脏标记，给出「已保存」轻提示。 */
async function save(): Promise<void> {
  await plan.flush()
  showToast('已保存')
}

/** 焦点是否处于输入控件内：除 Ctrl+S 外的快捷键不拦截输入。 */
function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
    || el.tagName === 'SELECT' || el.isContentEditable
}

function onKeydown(e: KeyboardEvent): void {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return
  const key = e.key.toLowerCase()
  // Ctrl+S / Cmd+S：输入框内也拦截，立即保存
  if (key === 's') {
    e.preventDefault()
    void save()
    return
  }
  if (e.shiftKey || isTyping(e.target)) return
  if (key === 'z') {
    e.preventDefault()
    void board.value?.undoLast()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  try {
    trip.value = await api.get<Trip>(`/trips/${tripId.value}`)
  } catch {
    // 标题获取失败不阻断看板：PlanBoard 会自行加载 /plan 并展示错误
  }
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

// 路由离开：有未提交变更时先等待全部写请求落库，再放行并给出「已保存」轻提示
onBeforeRouteLeave(async () => {
  if (plan.dirty) {
    showToast('已保存')
    await plan.flush()
  }
  return true
})

// 卸载兜底（非路由跳转场景）：同样确保写请求被等待
onBeforeUnmount(() => {
  if (plan.dirty) void plan.flush()
})
</script>

<template>
  <div v-if="deleteError" class="border-b border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
    {{ deleteError }}
  </div>
  <PlanBoard ref="board" :trip-id="tripId" :title="trip?.title ?? ''" @request-delete-trip="deleteOpen = true" />

  <ConfirmDialog
    v-model="deleteOpen"
    title="确定要删除这个行程吗？"
    :message="`删除「${trip?.title ?? '该行程'}」后，该行程及其内容将不再显示。`"
    confirm-text="是"
    cancel-text="否"
    danger
    :busy="deleting"
    @confirm="confirmDeleteTrip"
  />
</template>
