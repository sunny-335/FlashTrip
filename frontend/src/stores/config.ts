/** 安装向导状态、配置预设与 test-* / install 请求封装。字段名严格对齐后端契约。 */
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

// ---- AI 供应商预设：base_url 可覆盖；模型名一律来自 /models 或手填，绝不硬编码 ----
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

/**
 * 地图供应商预设：只保留品牌名与只读元数据（署名词 / 审图号）。
 * 样式地址、瓦片模板、坐标系、是否需要密钥等技术字段一律由后端预设自动带出，
 * 前端不再手填、也不在下拉里展示内部状态。id 与后端 PROVIDER_DEFS 严格一致。
 */
export interface MapPreset {
  id: string
  label: string
  attribution: string
  auditNumber: string
  needsKey: boolean
}
export const MAP_PRESETS: MapPreset[] = [
  { id: 'amap', label: '高德地图', attribution: '© 高德地图', auditNumber: '', needsKey: false },
  { id: 'tianditu', label: '天地图', attribution: '© 天地图', auditNumber: '', needsKey: true },
]

/** 邮件配置：与后端 mail 段字段一致；password 留空表示保留已保存密文。 */
export interface MailConfigIn {
  enabled: boolean
  host: string
  port: number
  user: string
  password: string
  from_addr: string
  from_name: string
  use_ssl: boolean
  use_tls: boolean
  timeout_s: number
  default_recipients: string[]
}
export function createMailConfig(): MailConfigIn {
  return {
    enabled: false,
    host: '',
    port: 465,
    user: '',
    password: '',
    from_addr: '',
    from_name: '瞬旅 FlashTrip',
    use_ssl: true,
    use_tls: false,
    timeout_s: 10,
    default_recipients: [],
  }
}

// ---- 与后端 InstallIn / ConfigUpdateIn 一致 ----
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
/** 设置页 / 向导只提交 id、密钥与启用开关，技术元数据由后端预设带出。 */
export interface MapProviderIn {
  id: string
  key: string
  enabled: boolean
}
export interface InstallIn {
  /** 兼容字段：完整连接串。结构化字段齐全时后端优先使用结构化字段。 */
  database_url: string
  database_dialect: string
  /** 结构化数据库字段（PostgreSQL 外部地址）。 */
  db_host: string
  db_port: number
  db_username: string
  db_password: string
  db_name: string
  redis_url: string
  redis_enabled: boolean
  /** 结构化 Redis 字段。 */
  redis_host: string
  redis_port: number
  redis_password: string
  redis_db: number
  admin: AdminIn
  ai_providers: AiProviderIn[]
  map_providers: MapProviderIn[]
  map_default_provider_id: string
  audit_number: string
  ai_tools_enabled: boolean
  secret_key: string
  /** 邮件配置：跳过时为 null；未跳过时并入安装请求，安装完成后亦可在设置页修改。 */
  mail: MailConfigIn | null
  mail_skipped: boolean
}

// ---- test-* 响应 ----
export interface DbTestResult { ok: boolean; dialect: string; version: string }
export interface RedisTestResult { ok: boolean; enabled: boolean; message?: string }
export interface AiTestResult { ok: boolean; models: string[] }
export interface MapTestResult { ok: boolean; status_code?: number; skipped?: boolean; message?: string }
export interface MailTestResult { ok: boolean; message: string }
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
  /** 管理员密码是否达到四类字符 / 长度 / 无连续串的强制标准，由 PasswordStrength 回传。 */
  adminMeetsPolicy: boolean
  secretBackedUp: boolean
  secretVisible: boolean
}

/** 初始安装表单：数据库默认 SQLite；AI/Map 各预置一条可编辑配置；邮件默认不跳过。 */
export function createInstallForm(): InstallIn {
  return {
    database_url: '',
    database_dialect: '',
    db_host: '',
    db_port: 5432,
    db_username: '',
    db_password: '',
    db_name: 'flashtrip',
    redis_url: '',
    redis_enabled: false,
    redis_host: '',
    redis_port: 6379,
    redis_password: '',
    redis_db: 0,
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
      { id: MAP_PRESETS[0].id, key: '', enabled: true },
    ],
    map_default_provider_id: MAP_PRESETS[0].id,
    audit_number: '',
    ai_tools_enabled: true,
    secret_key: '',
    mail: createMailConfig(),
    mail_skipped: false,
  }
}

export function createWizardProbe(): WizardProbe {
  return {
    db: { ok: false, dialect: '', version: '', error: '', tested: false },
    redis: { ok: false, enabled: false, error: '', skipped: true, tested: false },
    ai: { ok: false, models: [], error: '', skipped: false, tested: false },
    map: { ok: false, status: 0, error: '', skipped: false, tested: false },
    adminConfirm: '',
    adminMeetsPolicy: false,
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

/**
 * 装配最终提交体：跳过项清空、派生字段同步、邮件配置并入安装请求。
 * 由 InstallWizard 在 POST /wizard/install 前调用。
 */
export function buildPayload(form: InstallIn, probe: WizardProbe): InstallIn {
  const payload: InstallIn = JSON.parse(JSON.stringify(form)) as InstallIn
  payload.ai_providers = probe.ai.skipped
    ? []
    : payload.ai_providers.filter((p) => p.base_url.trim())
  if (payload.map_providers[0]) {
    payload.map_default_provider_id = payload.map_providers[0].id
  }
  // Redis：填写地址即启用；未填写地址或未通过测试则视为关闭
  payload.redis_enabled = payload.redis_host.trim().length > 0 && probe.redis.ok
  if (!payload.redis_enabled) {
    payload.redis_url = ''
    payload.redis_password = ''
  }
  // SQLite 由后端固定为数据目录单文件，前端不提交连接串
  if (payload.database_dialect !== 'postgresql') {
    payload.database_url = ''
    payload.db_host = ''
    payload.db_username = ''
    payload.db_password = ''
  }
  payload.database_dialect = probe.db.dialect || payload.database_dialect
  // 跳过邮件时只带 mail_skipped 标记，不提交半填的 SMTP 配置
  if (payload.mail_skipped) payload.mail = null
  return payload
}

export const useConfigStore = defineStore('config', () => {
  const status = ref<WizardStatus | null>(null)

  async function loadStatus(): Promise<WizardStatus> {
    const s = await api.get<WizardStatus>('/wizard/status')
    status.value = s
    return s
  }

  /** 数据库探测：结构化字段（地址/端口/用户名/密码/库名），后端负责拼装连接串。 */
  const testDb = (payload: {
    dialect?: string
    host?: string
    port?: number
    username?: string
    password?: string
    database?: string
    url?: string
  }) => api.post<DbTestResult>('/wizard/test-db', payload)
  /** Redis 探测：结构化字段（地址/端口/密码/库序号）。 */
  const testRedis = (payload: {
    host?: string
    port?: number
    password?: string
    database?: number
    url?: string
  }) => api.post<RedisTestResult>('/wizard/test-redis', payload)
  const testAi = (payload: { base_url: string; api_key: string; timeout_s?: number }) =>
    api.post<AiTestResult>('/wizard/test-ai', { timeout_s: 10, ...payload })
  /** 只传 provider_id，连通性地址由后端预设带出，不再提交任何手填 URL。 */
  const testMap = (payload: { provider_id: string; key?: string }) =>
    api.post<MapTestResult>('/wizard/test-map', payload)
  const testMail = (payload: MailConfigIn) =>
    api.post<MailTestResult>('/wizard/test-mail', payload)
  const install = (payload: InstallIn) => api.post<InstallResult>('/wizard/install', payload)

  return { status, loadStatus, testDb, testRedis, testAi, testMap, testMail, install }
})
