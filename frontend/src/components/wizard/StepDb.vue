<script setup lang="ts">
/**
 * 第 1 步：数据库与缓存。
 * - SQLite：不展示连接串，由后端固定为数据目录下的单文件；
 * - PostgreSQL：只填地址、端口、用户名、密码与库名，连接串由后端拼装，
 *   测试连接时若库不存在会自动创建 flashtrip 库；
 * - Redis：同页配置地址、端口、密码与库序号，可留空不启用。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Database, CheckCircle2, Server } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import { useConfigStore, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const cfg = useConfigStore()
const testing = ref(false)
const redisTesting = ref(false)
const kind = ref<'sqlite' | 'postgresql'>('sqlite')

const kinds = [
  { value: 'sqlite', label: 'SQLite（默认，单文件）' },
  { value: 'postgresql', label: 'PostgreSQL（外部地址）' },
]

/** PostgreSQL 必填项是否齐全（地址 / 用户名）。 */
const pgReady = computed(() =>
  props.form.db_host.trim().length > 0 && props.form.db_username.trim().length > 0,
)

watch(kind, (v) => {
  props.form.database_dialect = v === 'sqlite' ? 'sqlite' : 'postgresql'
  // 任一字段变化都必须重新测试，避免拿旧结果静默放行
  props.probe.db.ok = false
  props.probe.db.tested = false
  props.probe.db.error = ''
  // SQLite 是本地单文件、切回后立即自动复测，省去手动再点一次
  if (v === 'sqlite') void test()
}, { immediate: true })

watch(() => [props.form.db_host, props.form.db_port, props.form.db_username,
  props.form.db_password, props.form.db_name], () => {
  props.probe.db.ok = false
  props.probe.db.tested = false
  props.probe.db.error = ''
})

watch(() => [props.form.redis_host, props.form.redis_port, props.form.redis_password,
  props.form.redis_db], () => {
  props.probe.redis.ok = false
  props.probe.redis.tested = false
  props.probe.redis.error = ''
})

async function test() {
  testing.value = true
  props.probe.db.error = ''
  props.probe.db.tested = true
  try {
    const r = await cfg.testDb({
      dialect: kind.value,
      host: props.form.db_host,
      port: props.form.db_port,
      username: props.form.db_username,
      password: props.form.db_password,
      database: props.form.db_name,
    })
    props.probe.db.ok = r.ok
    props.probe.db.dialect = r.dialect
    props.probe.db.version = r.version
    props.form.database_dialect = r.dialect || kind.value
    if (!r.ok) props.probe.db.error = '连接未通过'
  } catch (e) {
    props.probe.db.ok = false
    props.probe.db.error = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    testing.value = false
  }
}

async function testRedis() {
  redisTesting.value = true
  props.probe.redis.error = ''
  props.probe.redis.tested = true
  try {
    const r = await cfg.testRedis({
      host: props.form.redis_host,
      port: props.form.redis_port,
      password: props.form.redis_password,
      database: props.form.redis_db,
    })
    props.probe.redis.ok = r.ok
    props.probe.redis.enabled = r.enabled
    props.form.redis_enabled = r.enabled
  } catch (e) {
    props.probe.redis.ok = false
    props.probe.redis.error = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    redisTesting.value = false
  }
}

onMounted(() => {
  if (!props.probe.db.tested) void test()
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <Database class="mt-0.5 h-4 w-4 shrink-0" />
      <span>配置写入配置文件与数据库双份，镜像不捆绑数据库。PostgreSQL 只需填写地址与账号密码，测试连接时若目标库不存在会自动创建。</span>
    </div>

    <div class="space-y-1.5">
      <label class="text-xs font-medium">数据库类型</label>
      <Select v-model="kind" :options="kinds" />
    </div>

    <!-- SQLite：不需要连接串 -->
    <div v-if="kind === 'sqlite'" class="rounded-lg border border-border bg-card p-3 text-xs leading-relaxed text-muted-foreground">
      使用 SQLite 单文件数据库，保存在数据卷目录中，无需填写任何连接信息。
      <span class="mt-1 block font-mono text-[11px] text-foreground">/data/flashtrip.db</span>
    </div>

    <!-- PostgreSQL：结构化字段 -->
    <div v-else class="space-y-3">
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">数据库地址 <span class="text-destructive">*</span></label>
          <Input v-model="form.db_host" placeholder="例如 db.example.com 或 192.168.1.10" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">端口</label>
          <Input v-model.number="form.db_port" type="number" placeholder="5432" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">用户名 <span class="text-destructive">*</span></label>
          <Input v-model="form.db_username" placeholder="数据库账号" autocomplete="username" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">密码</label>
          <Input v-model="form.db_password" type="password" placeholder="数据库密码" autocomplete="new-password" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">数据库名</label>
          <Input v-model="form.db_name" placeholder="flashtrip" />
        </div>
      </div>
      <p class="text-[11px] text-muted-foreground">地址与账号信息由服务端自动拼装并加密保存，无需手写。</p>
    </div>

    <div class="flex items-center gap-2">
      <Button variant="outline" size="sm" :disabled="testing || (kind === 'postgresql' && !pgReady)" @click="test">
        {{ testing ? '测试中…' : '测试连接' }}
      </Button>
      <span v-if="probe.db.ok" class="inline-flex items-center gap-1 text-xs text-primary">
        <CheckCircle2 class="h-3.5 w-3.5" /> 连接成功
        <Badge variant="outline">{{ probe.db.dialect }}</Badge>
      </span>
    </div>

    <div v-if="probe.db.ok && probe.db.version" class="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
      服务端版本：<span class="font-mono text-foreground">{{ probe.db.version }}</span>
    </div>
    <div v-if="probe.db.error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      {{ probe.db.error }}
    </div>

    <!-- Redis：与数据库同页配置 -->
    <div class="border-t border-border pt-4">
      <div class="mb-3 flex items-start gap-2">
        <Server class="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div>
          <p class="text-xs font-medium">Redis（可选）</p>
          <p class="mt-0.5 text-[11px] text-muted-foreground">
            留空则不启用，改用进程内事件总线；启用后填写地址与端口。
          </p>
        </div>
      </div>
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="space-y-1.5">
          <label class="text-xs font-medium">Redis 地址</label>
          <Input v-model="form.redis_host" placeholder="例如 127.0.0.1" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">端口</label>
          <Input v-model.number="form.redis_port" type="number" placeholder="6379" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">密码</label>
          <Input v-model="form.redis_password" type="password" placeholder="留空表示无需密码" autocomplete="new-password" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium">库序号</label>
          <Input v-model.number="form.redis_db" type="number" placeholder="0" />
        </div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="redisTesting || !form.redis_host.trim()" @click="testRedis">
          {{ redisTesting ? '测试中…' : '测试 Redis' }}
        </Button>
        <span v-if="probe.redis.ok" class="inline-flex items-center gap-1 text-xs text-primary">
          <CheckCircle2 class="h-3.5 w-3.5" /> 连接成功
        </span>
      </div>
      <p v-if="probe.redis.error" class="mt-2 text-xs text-destructive">{{ probe.redis.error }}</p>
    </div>
  </div>
</template>
