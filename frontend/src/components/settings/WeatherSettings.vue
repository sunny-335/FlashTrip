<script setup lang="ts">
/**
 * 天气配置：UApi Pro / 高德地图 / 和风天气三家供应商、密钥、缓存与提醒天数；
 * 「测试查询」调 /weather/forecast 展示当前天气与 7 天预报卡片。
 * 出行建议邮件的发送按钮由行程页提供，此处只给出中文说明。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { CloudSun, Save, Loader2, Search, ExternalLink } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import MarkdownText from '@/components/common/MarkdownText.vue'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'

interface WeatherConfig {
  provider: string
  cache_minutes: number
  advice_days: number
  has_amap_key: boolean
  has_qweather_key: boolean
  has_qweather_jwt: boolean
  has_uapi_key: boolean
  qweather_host: string
  daily_reminder_enabled: boolean
  daily_reminder_time: string
}
interface WeatherProvider { id: string; label: string; needs_key: boolean }
interface ProvidersResp { providers?: WeatherProvider[] }
interface CurrentWeather {
  weather: string
  temperature: number
  humidity: number
  wind: string
  report_time: string
  alerts: string[]
}
interface ForecastDay {
  date: string
  week: string
  weather_day: string
  weather_night: string
  temp_max: number
  temp_min: number
  wind: string
  pop: number
  uv: number
}
interface ForecastResult {
  provider: string
  city: string
  current: CurrentWeather
  forecast: ForecastDay[]
  advice_hints: string[]
  cached: boolean
}

const FALLBACK_PROVIDERS: WeatherProvider[] = [
  { id: 'uapis', label: 'UApi Pro', needs_key: false },
  { id: 'amap', label: '高德地图', needs_key: true },
  { id: 'qweather', label: '和风天气', needs_key: true },
]

const form = reactive({
  provider: 'uapis',
  amap_key: '',
  qweather_key: '',
  qweather_jwt: '',
  uapi_key: '',
  qweather_host: '',
  daily_reminder_enabled: false,
  daily_reminder_time: '07:30',
  cache_minutes: 60,
  advice_days: 1,
})
const providers = ref<WeatherProvider[]>(FALLBACK_PROVIDERS)
const keyState = reactive({ amap: false, qweather: false, qweatherJwt: false, uapi: false })
const toast = useToastStore()
const city = ref('')
const forecast = ref<ForecastResult | null>(null)
const loading = ref(true)
const saving = ref(false)
const querying = ref(false)
const ready = ref(false)

const providerOptions = computed(() => providers.value.map((p) => ({ value: p.id, label: p.label })))

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function popLabel(v: number): string {
  if (v === undefined || v === null || Number.isNaN(v)) return '—'
  return `${v <= 1 ? Math.round(v * 100) : Math.round(v)}%`
}
function tempLabel(v: number): string {
  return Number.isFinite(v) ? `${Math.round(v)}℃` : '—'
}

async function load() {
  loading.value = true
  try {
    const [cfg, providerResp] = await Promise.all([
      api.get<WeatherConfig>('/weather/config'),
      api.get<WeatherProvider[] | ProvidersResp>('/weather/providers').catch(() => null),
    ])
    form.provider = cfg.provider || 'uapis'
    form.cache_minutes = cfg.cache_minutes || 60
    form.advice_days = cfg.advice_days ?? 1
    form.qweather_host = cfg.qweather_host || ''
    form.daily_reminder_enabled = Boolean(cfg.daily_reminder_enabled)
    form.daily_reminder_time = cfg.daily_reminder_time || '07:30'
    form.amap_key = ''
    form.qweather_key = ''
    form.qweather_jwt = ''
    form.uapi_key = ''
    keyState.amap = Boolean(cfg.has_amap_key)
    keyState.qweather = Boolean(cfg.has_qweather_key)
    keyState.qweatherJwt = Boolean(cfg.has_qweather_jwt)
    keyState.uapi = Boolean(cfg.has_uapi_key)
    const list = Array.isArray(providerResp)
      ? providerResp
      : providerResp?.providers ?? []
    if (list.length) providers.value = list
    ready.value = true
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value || !ready.value) return
  saving.value = true
  try {
    await api.put('/weather/config', {
      provider: form.provider,
      amap_key: form.amap_key,
      qweather_key: form.qweather_key,
      qweather_jwt: form.qweather_jwt,
      qweather_host: form.qweather_host.trim(),
      daily_reminder_enabled: form.daily_reminder_enabled,
      daily_reminder_time: form.daily_reminder_time,
      uapi_key: form.uapi_key,
      cache_minutes: Number(form.cache_minutes) || 60,
      advice_days: Number(form.advice_days) || 1,
    })
    form.amap_key = ''
    form.qweather_key = ''
    form.qweather_jwt = ''
    form.uapi_key = ''
    toast.success('天气配置已保存')
    await load()
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    saving.value = false
  }
}

async function query() {
  if (!city.value.trim() || querying.value) return
  querying.value = true
  forecast.value = null
  try {
    const params = new URLSearchParams({
      city: city.value.trim(),
      days: '7',
      provider: form.provider,
    })
    forecast.value = await api.get<ForecastResult>(`/weather/forecast?${params.toString()}`)
  } catch (e) {
    toast.error(messageOf(e))
  } finally {
    querying.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">

    <!-- 供应商与密钥 -->
    <Card class="space-y-3">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="flex items-center gap-2 text-sm font-semibold text-foreground">
            <CloudSun class="h-4 w-4 text-primary" /> 天气
          </h2>
          <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
            选择天气数据来源并配置密钥。密钥加密存于服务端，输入框留空即保留已保存的密钥。
          </p>
        </div>
        <Button size="sm" :disabled="saving || loading || !ready" @click="save">
          <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
          <Save v-else class="h-3.5 w-3.5" /> 保存
        </Button>
      </div>

      <p v-if="loading" class="text-xs text-muted-foreground">正在读取天气配置…</p>
      <Button v-else-if="!ready" variant="outline" size="sm" @click="load">重新读取配置</Button>
      <template v-else>
        <div class="grid gap-2 sm:grid-cols-2">
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">天气供应商</label>
            <Select v-model="form.provider" :options="providerOptions" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">缓存时长（分钟）</label>
            <Input v-model="form.cache_minutes" type="number" placeholder="60" />
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">出行提醒提前天数</label>
            <Input v-model="form.advice_days" type="number" placeholder="1" />
          </div>
          <template v-if="form.provider === 'qweather'">
            <div class="space-y-1">
              <label class="text-[11px] text-muted-foreground">和风天气 API Host</label>
              <Input v-model="form.qweather_host" placeholder="账号专属 Host 域名" />
            </div>
            <div class="space-y-1">
              <label class="text-[11px] text-muted-foreground">和风 API Key</label>
              <Input v-model="form.qweather_key" type="password" autocomplete="new-password" placeholder="留空保留原值" />
              <p class="text-[10px] text-muted-foreground">{{ keyState.qweather ? '服务端已配置' : '尚未配置' }}</p>
            </div>
            <div class="space-y-1 sm:col-span-2">
              <label class="text-[11px] text-muted-foreground">和风 JWT（可选替代凭据）</label>
              <Input v-model="form.qweather_jwt" type="password" autocomplete="new-password" placeholder="留空保留原值" />
              <p class="text-[10px] text-muted-foreground">{{ keyState.qweatherJwt ? '服务端已配置' : '尚未配置' }}</p>
            </div>
          </template>
          <label class="flex items-center gap-2 text-xs sm:col-span-2">
            <input v-model="form.daily_reminder_enabled" type="checkbox" class="h-3.5 w-3.5" />
            启用旅行中的每日天气邮件提醒
          </label>
          <div v-if="form.daily_reminder_enabled" class="space-y-1 sm:col-span-2">
            <label class="text-[11px] text-muted-foreground">发送时间（24 小时制）</label>
            <Input v-model="form.daily_reminder_time" type="time" />
            <p class="text-[10px] text-muted-foreground">发送给行程所有者、成员及邮件设置中的默认收件人。</p>
          </div>
        </div>

        <p v-if="form.provider === 'uapis'" class="rounded-md border border-primary/30 bg-accent/50 px-2.5 py-2 text-[11px] leading-relaxed text-accent-foreground">
          UApi Pro 无需密钥即可使用；如需更高调用额度，可在下方填写可选密钥。
          <a
            href="https://uapis.cn/docs/api-reference/get-misc-weather"
            target="_blank"
            rel="noopener noreferrer"
            class="ml-1 inline-flex items-center gap-0.5 underline"
          >
            查看 UApi Pro 接口文档 <ExternalLink class="h-3 w-3" />
          </a>
        </p>

        <div class="grid gap-2 sm:grid-cols-3">
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">高德地图密钥</label>
            <Input v-model="form.amap_key" type="password" placeholder="留空保留原密钥" autocomplete="new-password" />
            <p class="text-[10px] text-muted-foreground">{{ keyState.amap ? '服务端已保存' : '尚未配置' }}</p>
          </div>
          <div class="space-y-1">
            <label class="text-[11px] text-muted-foreground">UApi Pro 密钥（可选）</label>
            <Input v-model="form.uapi_key" type="password" placeholder="留空保留原密钥" autocomplete="new-password" />
            <p class="text-[10px] text-muted-foreground">{{ keyState.uapi ? '服务端已保存' : '无需填写' }}</p>
          </div>
        </div>
      </template>
    </Card>

    <!-- 测试查询 -->
    <Card class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground">测试查询</h3>
      <div class="flex flex-col gap-2 sm:flex-row">
        <Input v-model="city" placeholder="输入城市名称，例如 杭州" @keydown.enter="query" />
        <Button size="sm" :disabled="querying || !city.trim()" class="shrink-0" @click="query">
          <Loader2 v-if="querying" class="h-3.5 w-3.5 animate-spin" />
          <Search v-else class="h-3.5 w-3.5" /> 查询天气
        </Button>
      </div>

      <template v-if="forecast">
        <div class="rounded-lg border border-border bg-muted/40 p-3">
          <div class="mb-2 flex items-center justify-between gap-2">
            <p class="text-xs font-medium text-foreground">{{ forecast.city }} · 当前天气</p>
            <Badge variant="outline">{{ forecast.cached ? '来自缓存' : '实时查询' }}</Badge>
          </div>
          <div class="grid gap-1.5 text-xs text-muted-foreground sm:grid-cols-2">
            <p>天气现象：<span class="text-foreground">{{ forecast.current.weather || '未知' }}</span></p>
            <p>气温：<span class="text-foreground">{{ tempLabel(forecast.current.temperature) }}</span></p>
            <p>湿度：<span class="text-foreground">{{ forecast.current.humidity }}%</span></p>
            <p>风况：<span class="text-foreground">{{ forecast.current.wind || '未知' }}</span></p>
            <p class="sm:col-span-2">发布时间：<span class="text-foreground">{{ forecast.current.report_time || '—' }}</span></p>
          </div>
          <p v-for="(a, i) in forecast.current.alerts ?? []" :key="i" class="mt-1.5 text-[11px] text-destructive">预警：{{ a }}</p>
        </div>

        <div>
          <p class="mb-2 text-xs font-medium text-foreground">未来 {{ forecast.forecast.length }} 天预报</p>
          <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="(f, i) in forecast.forecast" :key="i" class="rounded-lg border border-border bg-card p-2.5 text-xs">
              <p class="font-medium text-foreground">{{ f.week || f.date }} · {{ f.date }}</p>
              <p class="mt-1 text-muted-foreground">白天 {{ f.weather_day || '未知' }} / 夜间 {{ f.weather_night || '未知' }}</p>
              <p class="mt-1 text-foreground">{{ tempLabel(f.temp_max) }} / {{ tempLabel(f.temp_min) }}</p>
              <p class="mt-1 text-[11px] text-muted-foreground">
                降水 {{ popLabel(f.pop) }} · 紫外线 {{ f.uv || 0 }} · {{ f.wind || '风力未知' }}
              </p>
            </div>
          </div>
        </div>

        <div v-if="forecast.advice_hints?.length" class="rounded-lg border border-border bg-muted/40 p-3">
          <p class="mb-1 text-xs font-medium text-foreground">出行提示</p>
          <MarkdownText compact :source="forecast.advice_hints.map((hint) => `- ${hint}`).join('\n')" />
        </div>
      </template>
      <p v-else class="text-xs text-muted-foreground">输入城市后可查看当前天气与 7 天预报。</p>
    </Card>

    <!-- 出行建议说明 -->
    <Card class="space-y-2">
      <h3 class="text-sm font-semibold text-foreground">生成并发送出行建议</h3>
      <p class="text-xs leading-relaxed text-muted-foreground">
        在行程详情页可一键生成并发送出行建议邮件：系统结合目的地天气、行程日期与随行人数，
        生成中文的穿衣、雨具与装备建议，并发送给行程所有者、成员及邮件设置中的默认收件人。此处的按钮由行程页提供。
      </p>
    </Card>
  </div>
</template>
