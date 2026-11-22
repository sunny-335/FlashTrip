<script setup lang="ts">
/** 公开分享视图（standalone / public）：仅凭 token 读取只读行程快照。
 *  GET /share/{token} 不需要登录；渲染行程、交通、预订、物品、可选费用与对外瞬间。
 *  全程只读，无任何编辑或登录入口；链接失效时给出统一中文提示。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  CalendarDays, MapPin, Route, Hotel, Backpack, Wallet, Camera,
  Check, X, Loader2, Image as ImageIcon,
} from 'lucide-vue-next'
import { api } from '@/lib/api'

interface TripInfo {
  id: string
  title: string
  destination: string | null
  start_date: string | null
  end_date: string | null
  status: string
  cover_url: string | null
}
interface Transport {
  id: string
  mode: string
  from_name: string | null
  to_name: string | null
  depart_at: string | null
  arrive_at: string | null
  carrier: string | null
  seat: string | null
}
interface Booking {
  id: string
  type: string
  vendor: string | null
  holder: string | null
  start_at: string | null
  end_at: string | null
  status: string
  note: string | null
}
interface PackingGroup {
  list: { id: string; name: string }
  items: { id: string; name: string; qty: number; checked: boolean }[]
}
interface Expense {
  id: string
  category: string
  amount: number
  currency: string
  occurred_at: string | null
  note: string | null
}
interface Moment {
  id: string
  content: string | null
  mood: string | null
  lng: number | null
  lat: number | null
  taken_at: string | null
  media_json: string | null
}
interface ShareSnapshot {
  trip: TripInfo
  transports: Transport[]
  bookings: Booking[]
  packing: PackingGroup[]
  expenses: Expense[] | null
  moments: Moment[]
  generated_at: string
}

const route = useRoute()
const token = computed(() => String(route.params.token ?? ''))
const data = ref<ShareSnapshot | null>(null)
const loading = ref(true)
const error = ref('')
/** 点击瞬间图片放大查看（纯只读交互）。 */
const previewUrl = ref('')

const statusLabel: Record<string, string> = {
  planned: '计划中', ongoing: '进行中', completed: '已完成', archived: '已归档',
}
const modeLabel: Record<string, string> = {
  flight: '飞机', train: '火车', car: '自驾', bus: '大巴', ferry: '轮渡', walk: '步行', other: '其他',
}
const bookingTypeLabel: Record<string, string> = {
  flight: '机票', hotel: '酒店', train: '火车', ticket: '门票', other: '其他',
}
const bookingStatusLabel: Record<string, string> = {
  pending: '待确认', confirmed: '已确认', cancelled: '已取消',
}
const categoryLabel: Record<string, string> = {
  food: '餐饮', lodging: '住宿', transport: '交通', ticket: '门票', shopping: '购物', other: '其他',
}

/** 中文日期：ISO 日期转「2026年5月1日」，空值显示占位。 */
function formatDay(v: string | null): string {
  if (!v) return '未填写'
  const parts = v.slice(0, 10).split('-')
  if (parts.length !== 3) return v
  return `${parts[0]}年${Number(parts[1])}月${Number(parts[2])}日`
}

/** 中文日期时间：ISO 时间戳只展示到分钟。 */
function formatMoment(v: string | null): string {
  if (!v) return ''
  const [d, t] = v.replace('T', ' ').split(' ')
  const parts = (d || '').split('-')
  const day = parts.length === 3 ? `${parts[0]}年${Number(parts[1])}月${Number(parts[2])}日` : d
  return `${day} ${(t || '').slice(0, 5)}`.trim()
}

/** 生成时间来自服务端，按原样展示并附中文说明。 */
const generatedText = computed(() => {
  const raw = data.value?.generated_at
  if (!raw) return '—'
  return formatMoment(raw)
})

/** media_json 为附件 ID 的 JSON 数组字符串；解析失败按无图片处理。 */
function mediaIds(m: Moment): string[] {
  if (!m.media_json) return []
  try {
    const parsed: unknown = JSON.parse(m.media_json)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((x): x is string => typeof x === 'string' && Boolean(x))
  } catch {
    return []
  }
}

/** 附件直接由后端 GET /uploads/{id} 返回文件，可作为图片地址。 */
function mediaUrl(id: string): string {
  return `/api/v1/uploads/${encodeURIComponent(id)}`
}

function hasMoments(): boolean {
  return Boolean(data.value?.moments?.length)
}
function hasPacking(): boolean {
  return Boolean(data.value?.packing?.length)
}

onMounted(async () => {
  try {
    data.value = await api.get<ShareSnapshot>(`/share/${encodeURIComponent(token.value)}`)
  } catch {
    // 无论后端返回何种错误码，分享页统一给出该中文提示，不泄露细节
    error.value = '分享链接无效或已过期'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <div class="mx-auto max-w-[900px] space-y-6 px-5 py-8">
      <!-- 品牌头 -->
      <header class="flex items-center justify-between gap-3 border-b border-border pb-4">
        <div class="flex items-center gap-2.5">
          <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">瞬</span>
          <div>
            <p class="text-sm font-semibold leading-tight">瞬旅 FlashTrip</p>
            <p class="text-[11px] text-muted-foreground">行程分享 · 只读</p>
          </div>
        </div>
        <span class="rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground">公开只读页面</span>
      </header>

      <!-- 加载 / 错误 -->
      <div v-if="loading" class="py-20 text-center text-sm text-muted-foreground">
        <Loader2 class="mx-auto mb-2 h-6 w-6 animate-spin" /> 正在打开分享内容…
      </div>
      <div v-else-if="error" class="py-20 text-center">
        <div class="mx-auto max-w-sm rounded-lg border border-border bg-card p-8 shadow-sm">
          <X class="mx-auto mb-3 h-7 w-7 text-destructive" />
          <p class="text-sm font-medium text-foreground">分享链接无效或已过期</p>
          <p class="mt-1.5 text-xs leading-relaxed text-muted-foreground">
            该链接可能已被撤销、超过有效期，或地址填写不完整。请向分享者索取新的链接。
          </p>
        </div>
      </div>

      <template v-else-if="data">
        <!-- 行程概览 -->
        <section class="overflow-hidden rounded-lg border border-border bg-card shadow-sm">
          <img v-if="data.trip.cover_url" :src="data.trip.cover_url" alt="行程封面" class="h-48 w-full object-cover" />
          <div class="p-5">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <h1 class="text-xl font-semibold">{{ data.trip.title || '未命名行程' }}</h1>
              <span class="rounded-md border border-border bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                {{ statusLabel[data.trip.status] ?? data.trip.status }}
              </span>
            </div>
            <div class="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
              <span v-if="data.trip.destination" class="inline-flex items-center gap-1">
                <MapPin class="h-3.5 w-3.5 text-primary" /> {{ data.trip.destination }}
              </span>
              <span class="inline-flex items-center gap-1">
                <CalendarDays class="h-3.5 w-3.5 text-primary" />
                {{ formatDay(data.trip.start_date) }} — {{ formatDay(data.trip.end_date) }}
              </span>
            </div>
          </div>
        </section>

        <!-- 交通 -->
        <section v-if="data.transports?.length" class="space-y-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Route class="h-4 w-4 text-primary" /> 交通安排</h2>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div v-for="t in data.transports" :key="t.id" class="rounded-lg border border-border bg-card p-3 shadow-sm">
              <div class="flex items-center gap-2 text-sm font-medium">
                <span class="rounded-md bg-accent px-1.5 py-0.5 text-[11px] text-accent-foreground">{{ modeLabel[t.mode] ?? t.mode }}</span>
                <span class="truncate">{{ t.from_name || '起点' }}</span>
                <span class="text-muted-foreground">→</span>
                <span class="truncate">{{ t.to_name || '终点' }}</span>
              </div>
              <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                {{ formatMoment(t.depart_at) || '未填出发时间' }}<span v-if="t.arrive_at"> → {{ formatMoment(t.arrive_at) }}</span>
                <span v-if="t.carrier"> · {{ t.carrier }}</span><span v-if="t.seat"> · {{ t.seat }}</span>
              </p>
            </div>
          </div>
        </section>

        <!-- 酒店 / 预订 -->
        <section v-if="data.bookings?.length" class="space-y-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Hotel class="h-4 w-4 text-primary" /> 酒店与预订</h2>
          <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-sm">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-border text-muted-foreground">
                <tr>
                  <th class="px-3 py-2 font-medium">类型 / 供应商</th>
                  <th class="px-3 py-2 font-medium">持有人</th>
                  <th class="px-3 py-2 font-medium">时间</th>
                  <th class="px-3 py-2 font-medium">状态</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr v-for="b in data.bookings" :key="b.id">
                  <td class="px-3 py-2">
                    <span class="font-medium text-foreground">{{ b.vendor || '未填写供应商' }}</span>
                    <span class="ml-1.5 text-[10px] text-muted-foreground">{{ bookingTypeLabel[b.type] ?? b.type }}</span>
                  </td>
                  <td class="px-3 py-2 text-muted-foreground">{{ b.holder || '—' }}</td>
                  <td class="px-3 py-2 text-muted-foreground">{{ formatMoment(b.start_at) || '—' }}</td>
                  <td class="px-3 py-2 text-muted-foreground">{{ bookingStatusLabel[b.status] ?? b.status }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- 物品清单 -->
        <section v-if="hasPacking()" class="space-y-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Backpack class="h-4 w-4 text-primary" /> 物品清单</h2>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="g in data.packing" :key="g.list.id" class="rounded-lg border border-border bg-card p-3 shadow-sm">
              <p class="mb-2 text-sm font-medium">{{ g.list.name }}</p>
              <div class="space-y-1">
                <div v-for="item in g.items" :key="item.id" class="flex items-center gap-1.5 text-xs">
                  <Check v-if="item.checked" class="h-3 w-3 shrink-0 text-primary" />
                  <X v-else class="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span :class="item.checked ? 'text-muted-foreground line-through' : 'text-foreground'">{{ item.name }}</span>
                  <span class="ml-auto text-[10px] text-muted-foreground">×{{ item.qty }}</span>
                </div>
                <p v-if="!g.items.length" class="text-[11px] text-muted-foreground">清单为空</p>
              </div>
            </div>
          </div>
        </section>

        <!-- 费用：分享者可选择不公开，此时后端返回 null -->
        <section v-if="data.expenses !== null" class="space-y-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Wallet class="h-4 w-4 text-primary" /> 费用明细</h2>
          <div class="overflow-x-auto rounded-lg border border-border bg-card shadow-sm">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-border text-muted-foreground">
                <tr>
                  <th class="px-3 py-2 font-medium">分类</th>
                  <th class="px-3 py-2 font-medium">金额</th>
                  <th class="px-3 py-2 font-medium">时间</th>
                  <th class="px-3 py-2 font-medium">备注</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr v-for="x in data.expenses ?? []" :key="x.id">
                  <td class="px-3 py-2 text-foreground">{{ categoryLabel[x.category] ?? x.category }}</td>
                  <td class="px-3 py-2 font-medium text-foreground">{{ x.currency }} {{ Number(x.amount).toFixed(2) }}</td>
                  <td class="px-3 py-2 text-muted-foreground">{{ formatMoment(x.occurred_at) || '—' }}</td>
                  <td class="px-3 py-2 text-muted-foreground">{{ x.note || '—' }}</td>
                </tr>
                <tr v-if="!data.expenses?.length">
                  <td colspan="4" class="px-3 py-4 text-center text-muted-foreground">暂无费用记录</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- 对外展示的瞬间 -->
        <section v-if="hasMoments()" class="space-y-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold"><Camera class="h-4 w-4 text-primary" /> 旅途瞬间</h2>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <article v-for="m in data.moments" :key="m.id" class="rounded-lg border border-border bg-card p-3.5 shadow-sm">
              <p class="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{{ m.content || '（无文字）' }}</p>
              <div v-if="mediaIds(m).length" class="mt-2.5 grid grid-cols-3 gap-1.5">
                <button
                  v-for="id in mediaIds(m)"
                  :key="id"
                  class="aspect-square overflow-hidden rounded-md border border-border bg-muted"
                  @click="previewUrl = mediaUrl(id)"
                >
                  <img :src="mediaUrl(id)" alt="瞬间图片" class="h-full w-full object-cover" />
                </button>
              </div>
              <div class="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <span v-if="m.taken_at">{{ formatMoment(m.taken_at) }}</span>
                <span v-if="m.mood" class="rounded-md border border-border px-1.5 py-0.5">{{ m.mood }}</span>
                <span v-if="m.lng !== null && m.lat !== null" class="inline-flex items-center gap-0.5">
                  <MapPin class="h-3 w-3" /> {{ Number(m.lng).toFixed(4) }}, {{ Number(m.lat).toFixed(4) }}
                </span>
              </div>
            </article>
          </div>
        </section>

        <!-- 全部分区都为空时的兜底 -->
        <div
          v-if="!data.transports?.length && !data.bookings?.length && !hasPacking() && data.expenses === null && !hasMoments()"
          class="rounded-lg border border-dashed border-border bg-card/50 px-6 py-10 text-center"
        >
          <ImageIcon class="mx-auto mb-2 h-7 w-7 text-muted-foreground" />
          <p class="text-sm text-muted-foreground">这份分享暂未包含可展示的内容。</p>
        </div>

        <!-- 页脚 -->
        <footer class="border-t border-border pt-4 text-center text-[11px] leading-relaxed text-muted-foreground">
          <p>由 瞬旅 FlashTrip 生成</p>
          <p class="mt-0.5">生成时间：{{ generatedText }}</p>
        </footer>
      </template>
    </div>

    <!-- 图片放大查看：点击遮罩关闭，纯只读 -->
    <div
      v-if="previewUrl"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      @click="previewUrl = ''"
    >
      <img :src="previewUrl" alt="瞬间图片大图" class="max-h-full max-w-full rounded-lg object-contain shadow-lg" @click.stop />
      <button class="absolute right-5 top-5 rounded-lg border border-white/40 bg-black/40 p-2 text-white" aria-label="关闭" @click="previewUrl = ''">
        <X class="h-5 w-5" />
      </button>
    </div>
  </div>
</template>
