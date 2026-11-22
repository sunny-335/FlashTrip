/** 拖拽命令栈：记录每次移动前的快照，供 Ctrl+Z / 撤销按钮逐级回退。 */
import { computed, shallowRef } from 'vue'

export interface MoveCommand<S> {
  label: string
  /** 该命令执行前的完整数据快照，用于乐观恢复。 */
  snapshot: S
  moves: unknown[]
}

export function useUndoableMoves<S>() {
  const stack = shallowRef<MoveCommand<S>[]>([])
  const canUndo = computed(() => stack.value.length > 0)
  const depth = computed(() => stack.value.length)

  function push(cmd: MoveCommand<S>): void {
    stack.value = [...stack.value, cmd]
  }

  /** 弹出最近一条命令；栈空返回 undefined。 */
  function pop(): MoveCommand<S> | undefined {
    const next = [...stack.value]
    const cmd = next.pop()
    stack.value = next
    return cmd
  }

  function clear(): void {
    stack.value = []
  }

  return { stack, canUndo, depth, push, pop, clear }
}
