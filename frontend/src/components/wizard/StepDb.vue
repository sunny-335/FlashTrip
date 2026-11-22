<script setup lang="ts">
/** 第 1 步：数据库连接。默认 SQLite；可切外部 PostgreSQL。进入即自动测一次 SELECT 1。 */
import { onMounted, ref, watch } from 'vue'
import { Database, CheckCircle2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import { useConfigStore, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const cfg = useConfigStore()
const testing = ref(false)
const kind = ref('sqlite')

const kinds = [
  { value: 'sqlite', label: 'SQLite（默认，单文件）' },
  { value: 'postgresql', label: 'PostgreSQL（外部地址）' },
]

watch(kind, (v) => {
  props.form.database_url = v === 'sqlite'
    ? 'sqlite:////data/flashtrip.db'
    : 'postgresql://user:password@host:5432/flashtrip'
  props.form.database_dialect = ''
})
// 连接串变更必须重新测试，避免拿旧结果静默放行
watch(() => props.form.database_url, () => {
  props.probe.db.ok = false
  props.probe.db.tested = false
})

async function test() {
  testing.value = true
  props.probe.db.error = ''
  props.probe.db.tested = true
  try {
    const r = await cfg.testDb(props.form.database_url)
    props.probe.db.ok = r.ok
    props.probe.db.dialect = r.dialect
    props.probe.db.version = r.version
    props.form.database_dialect = r.dialect
    if (!r.ok) props.probe.db.error = '连接未通过'
  } catch (e) {
    props.probe.db.ok = false
    props.probe.db.error = e instanceof ApiError ? e.message : (e as Error).message
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  if (!props.probe.db.tested) void test()
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <Database class="mt-0.5 h-4 w-4 shrink-0" />
      <span>连接串会先于数据库写入配置文件（config.json）。镜像不捆绑数据库；PostgreSQL 仅填写外部地址，3 秒连通超时。</span>
    </div>

    <div class="space-y-1.5">
      <label class="text-xs font-medium">数据库类型</label>
      <Select v-model="kind" :options="kinds" />
    </div>
    <div class="space-y-1.5">
      <label class="text-xs font-medium">连接串</label>
      <Input v-model="form.database_url" placeholder="sqlite:////data/flashtrip.db" :invalid="Boolean(probe.db.error)" />
      <p class="text-[11px] text-muted-foreground">修改后需重新测试连接。</p>
    </div>

    <div class="flex items-center gap-2">
      <Button variant="outline" size="sm" :disabled="testing" @click="test">
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
  </div>
</template>
