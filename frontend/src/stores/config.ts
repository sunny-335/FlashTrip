/** 安装向导状态、配置预设与 test-* / install 请求封装。字段名严格对齐 install_service.py。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/lib/api'

export interface WizardStep {
  key: string
  label: string
  done: boolean
}
export interface WizardStatus {
  installed: boolean
  unlocked: boolean
  steps: WizardStep[]
  version: string
}

// ---- 供应商预设：base_url 可覆盖；模型名一律来自 /models 或手填，绝不硬编码 ----
export interface AiPreset {
  id: string
  label: string
  base_url: string
  needs_token: boolean
}
export const AI_PRESETS: AiPreset[] = [
  { id: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com', needs_token: true },
  { id: 'qwen', label: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', needs_token: true },
  { id: 'kimi', label: 'Kimi', base_url: 'https://api.moonshot.cn/v1', needs_token: true },
  { id: 'mimo', label: 'MiMo', base_url: 'https://api.xiaomimimo.com/v1', needs_token: true },
  { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', needs_token: true },
  { id: 'custom', label: '自定义（兼容 OpenAI /v1）', base_url: '', needs_token: true },
]

export interface MapPreset {
  id: string
  label: string
  style_url: string
  tile_url_template: string
  coord_system: string
  attribution: string
  needs_token: boolean
}
// 仅 OpenFreeMap 提供确切免 token 底图地址；其余留空由用户在向导填写，不臆造瓦片 URL。
export const MAP_PRESETS: MapPreset[] = [
  {
    id: 'openfreemap',
    label: 'OpenFreeMap · Liberty（免 token，境外合规）',
    style_url: 'https://tiles.openfreemap.org/styles/liberty',
    tile_url_template: '',
    coord_system: 'WGS84',
    attribution: '© OpenFreeMap · © OpenStreetMap contributors',
    needs_token: false,
  },
  { id: 'amap', label: '高德（GCJ-02，需 key）', style_url: '', tile_url_template: '', coord_system: 'GCJ-02', attribution: '© 高德地图', needs_token: true },
  { id: 'baidu', label: '百度（BD-09，需 key）', style_url: '', tile_url_template: '', coord_system: 'BD-09', attribution: '© 百度地图', needs_token: true },
  { id: 'tianditu', label: '天地图（CGCS2000，需 key）', style_url: '', tile_url_template: '', coord_system: 'CGCS2000', attribution: '© 天地图', needs_token: true },
  { id: 'mapbox', label: 'Mapbox（需 token）', style_url: '', tile_url_template: '', coord_system: 'WGS84', attribution: '© Mapbox', needs_token: true },
]

// ---- 与 install_service.InstallIn 一致 ----
export interface AdminIn {
  username: string
  password: string
  email: string | null
  phone: string | null
  display_name: string
}
export interface AiProviderIn {
  id: string
  base_url: string
  api_key: string
  model: string
  enabled: boolean
  priority: number
  timeout_s: number
  supports_stream: boolean
}
export interface MapProviderIn {
  id: string
  key: string
  style_url: string
  tile_url_template: string
  default_style: string
  coord_system: string
  attribution: string
  audit_number: string
  enabled: boolean
  needs_token: boolean
}
export interface InstallIn {
  database_url: string
  database_dialect: string
  redis_url: string
  redis_enabled: boolean
  admin: AdminIn
  ai_providers: AiProviderIn[]
  map_providers: MapProviderIn[]
  map_default_provider_id: string
  audit_number: string
  ai_tools_enabled: boolean
  secret_key: string
}

// ---- test-* 响应 ----
export interface DbTestResult { ok: boolean; dialect: string; version: string }
export interface RedisTestResult { ok: boolean; enabled: boolean; message?: string }
export interface AiTestResult { ok: boolean; models: string[] }
export interface MapTestResult { ok: boolean; status_code?: number; skipped?: boolean; message?: string }
export interface InstallResult {
  installed: boolean
  need_backup_secret: boolean
  secret_key?: string
}

/** 向导各步的探测结果 / UI 辅助状态（跨步骤保留，切步不丢）。 */
export interface WizardProbe {
  db: { ok: boolean; dialect: string; version: string; error: string; tested: boolean }
  redis: { ok: boolean; enabled: boolean; error: string; skipped: boolean; tested: boolean }
  ai: { ok: boolean; models: string[]; error: string; skipped: boolean; tested: boolean }
  map: { ok: boolean; status: number; error: string; skipped: boolean; tested: boolean }
  adminConfirm: string
  secretBackedUp: boolean
  secretVisible: boolean
}

/** 初始安装表单：数据库默认 SQLite；AI/Map 各预置一条可编辑配置。 */
export function createInstallForm(): InstallIn {
  return {
    database_url: 'sqlite:////data/flashtrip.db',
    database_dialect: '',
    redis_url: '',
    redis_enabled: false,
    admin: { username: '', password: '', email: null, phone: null, display_name: '' },
    ai_providers: [
      {
        id: AI_PRESETS[0].id,
        base_url: AI_PRESETS[0].base_url,
        api_key: '',
        model: '',
        enabled: true,
        priority: 0,
        timeout_s: 60,
        supports_stream: true,
      },
    ],
    map_providers: [
      {
        id: MAP_PRESETS[0].id,
        key: '',
        style_url: MAP_PRESETS[0].style_url,
        tile_url_template: '',
        default_style: 'liberty',
        coord_system: MAP_PRESETS[0].coord_system,
        attribution: MAP_PRESETS[0].attribution,
        audit_number: '',
        enabled: true,
        needs_token: MAP_PRESETS[0].needs_token,
      },
    ],
    map_default_provider_id: MAP_PRESETS[0].id,
    audit_number: '',
    ai_tools_enabled: false,
    secret_key: '',
  }
}

export function createWizardProbe(): WizardProbe {
  return {
    db: { ok: false, dialect: '', version: '', error: '', tested: false },
    redis: { ok: false, enabled: false, error: '', skipped: true, tested: false },
    ai: { ok: false, models: [], error: '', skipped: false, tested: false },
    map: { ok: false, status: 0, error: '', skipped: false, tested: false },
    adminConfirm: '',
    secretBackedUp: false,
    secretVisible: false,
  }
}

/** 生成 URL-safe 随机主密钥（与后端 secrets.token_urlsafe(48) 强度相当）。 */
export function generateSecretKey(): string {
  const bytes = new Uint8Array(48)
  crypto.getRandomValues(bytes)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export const useConfigStore = defineStore('config', () => {
  const status = ref<WizardStatus | null>(null)

  async function loadStatus(): Promise<WizardStatus> {
    const s = await api.get<WizardStatus>('/wizard/status')
    status.value = s
    return s
  }

  const testDb = (url: string) => api.post<DbTestResult>('/wizard/test-db', { url })
  const testRedis = (url: string) => api.post<RedisTestResult>('/wizard/test-redis', { url })
  const testAi = (payload: { base_url: string; api_key: string; timeout_s?: number }) =>
    api.post<AiTestResult>('/wizard/test-ai', { timeout_s: 10, ...payload })
  const testMap = (payload: { style_url: string; tile_url_template: string; key: string }) =>
    api.post<MapTestResult>('/wizard/test-map', payload)
  const install = (payload: InstallIn) => api.post<InstallResult>('/wizard/install', payload)

  return { status, loadStatus, testDb, testRedis, testAi, testMap, install }
})
