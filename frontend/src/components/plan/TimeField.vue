<script setup lang="ts">
/** 时间联动输入：开始 / 时长 / 结束三者互相推导，始终自洽。
 *  - 改「开始」或「时长」→ 自动算「结束」；改「结束」→ 自动反推「时长」；
 *  - 开始 / 结束用 type="time"（HH:mm），时长统一显示为 2h10m，
 *    输入兼容「2小时10分钟」「130」「2h10m」「1:30」等写法；
 *  - 对外以 ISO 字符串（startTime / endTime）与分钟数（durationMin）交互，
 *    日期取所在行程日的 date 拼 ISO（后端 normalize_times 会做最终兜底）。
 *  切换编辑对象时由父组件用 :key 重建，以载入新条目的时间。
 */
import { ref, watch } from 'vue'
import {
  formatDuration, parseDuration, toMinutes, minutesToClock, clockOfIso, combineIso,
} from '@/lib/time'

const props = withDefaults(defineProps<{ date?: string | null }>(), { date: null })
const startTime = defineModel<string | null>('startTime', { default: null })
const endTime = defineModel<string | null>('endTime', { default: null })
const durationMin = defineModel<number | null>('durationMin', { default: null })

const startClock = ref('')
const endClock = ref('')
const durationText = ref('')
const error = ref('')

function init(): void {
  startClock.value = clockOfIso(startTime.value)
  endClock.value = clockOfIso(endTime.value)
  durationText.value = durationMin.value == null ? '' : formatDuration(durationMin.value)
  error.value = ''
}
init()

/** 当前时长输入框解析出的分钟数；空串表示未设置。 */
function currentDuration(): number | null {
  if (!durationText.value.trim()) return null
  return parseDuration(durationText.value)
}

/** 把三个输入框的结果推给父组件（ISO 用行程日 date 拼接）。 */
function commit(): void {
  const s = startClock.value
  const e = endClock.value
  const dur = currentDuration()
  startTime.value = s ? combineIso(props.date, s, 0) : null
  if (e) {
    // 结束钟点早于开始：视为跨到次日，ISO 日期顺延一天
    const sm = toMinutes(s || '')
    const em = toMinutes(e)
    const offset = !Number.isNaN(sm) && !Number.isNaN(em) && em < sm ? 1 : 0
    endTime.value = combineIso(props.date, e, offset)
  } else {
    endTime.value = null
  }
  durationMin.value = dur
}

function onStartChange(v: string): void {
  startClock.value = v
  error.value = ''
  const dur = currentDuration()
  const sm = toMinutes(v)
  if (!Number.isNaN(sm) && dur !== null) {
    endClock.value = minutesToClock(sm + dur)
  } else if (!Number.isNaN(sm) && endClock.value) {
    const em = toMinutes(endClock.value)
    if (!Number.isNaN(em)) {
      const d = em >= sm ? em - sm : em + 1440 - sm
      durationText.value = formatDuration(d)
    }
  }
  commit()
}

function onDurationInput(): void {
  const dur = currentDuration()
  if (durationText.value.trim() && dur === null) {
    error.value = '时长格式无法识别，可用「2小时10分钟」「130」「2h10m」「1:30」'
    return
  }
  error.value = ''
  const sm = toMinutes(startClock.value)
  if (dur !== null && !Number.isNaN(sm)) {
    endClock.value = minutesToClock(sm + dur)
  } else if (dur !== null && endClock.value) {
    const em = toMinutes(endClock.value)
    if (!Number.isNaN(em)) startClock.value = minutesToClock(em - dur)
  }
  commit()
}

/** 失焦后把时长归一显示为 2h10m。 */
function onDurationBlur(): void {
  const dur = currentDuration()
  if (dur !== null) {
    durationText.value = formatDuration(dur)
    error.value = ''
  }
}

function onEndChange(v: string): void {
  endClock.value = v
  error.value = ''
  const em = toMinutes(v)
  const sm = toMinutes(startClock.value)
  if (!Number.isNaN(sm) && !Number.isNaN(em)) {
    const d = em >= sm ? em - sm : em + 1440 - sm
    durationText.value = formatDuration(d)
  } else if (!Number.isNaN(em)) {
    const dur = currentDuration()
    if (dur !== null) startClock.value = minutesToClock(em - dur)
  }
  commit()
}

// 所属行程日变化时，用新日期重新拼接 ISO（钟点不变）
watch(() => props.date, () => commit())
</script>

<template>
  <div class="space-y-1.5">
    <div class="grid grid-cols-3 gap-2">
      <div class="space-y-1">
        <label class="text-[11px] font-medium text-muted-foreground">开始</label>
        <input
          :value="startClock"
          type="time"
          class="h-9 w-full rounded-lg border border-input bg-card px-2 text-xs text-foreground shadow-sm outline-none transition focus-visible:ring-2 focus-visible:ring-ring"
          @change="onStartChange(($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="space-y-1">
        <label class="text-[11px] font-medium text-muted-foreground">时长</label>
        <input
          v-model="durationText"
          type="text"
          inputmode="text"
          placeholder="2小时10分钟"
          class="h-9 w-full rounded-lg border border-input bg-card px-2 text-xs text-foreground shadow-sm outline-none transition placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          @input="onDurationInput"
          @blur="onDurationBlur"
        />
      </div>
      <div class="space-y-1">
        <label class="text-[11px] font-medium text-muted-foreground">结束</label>
        <input
          :value="endClock"
          type="time"
          class="h-9 w-full rounded-lg border border-input bg-card px-2 text-xs text-foreground shadow-sm outline-none transition focus-visible:ring-2 focus-visible:ring-ring"
          @change="onEndChange(($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>
    <p v-if="error" class="text-[11px] text-destructive">{{ error }}</p>
    <p v-else class="text-[11px] leading-relaxed text-muted-foreground">
      时长可填「2小时10分钟」「130」「2h10m」「1:30」，统一显示为 2h10m；开始与时长会自动推算结束，改结束会反推时长。
    </p>
  </div>
</template>
