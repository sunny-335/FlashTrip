<script setup lang="ts">
/** 第 7 步：汇总脱敏配置，逐块可点「修改」回退到对应步骤。 */
import { computed } from 'vue'
import { Pencil } from 'lucide-vue-next'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { MAP_PRESETS, type InstallIn, type WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()
const emit = defineEmits<{ edit: [step: number] }>()

function maskUrl(u: string): string {
  return u.replace(/(\/\/[^:/@]+:)[^@]+@/, '$1••••@')
}
const aiSkipped = computed(() => props.probe.ai.skipped || props.form.ai_providers.length === 0)
const ai = computed(() => props.form.ai_providers[0])
const map = computed(() => props.form.map_providers[0])
const mapLabel = computed(() => MAP_PRESETS.find((p) => p.id === map.value?.id)?.label || map.value?.id || '未选择')
</script>

<template>
  <div class="space-y-3">
    <p class="text-xs text-muted-foreground">请核对以下配置。密钥类信息已脱敏；点击「修改」可回到对应步骤调整。</p>

    <Card class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">数据库</span>
        <button class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary" @click="emit('edit', 0)"><Pencil class="h-3 w-3" />修改</button>
      </div>
      <p class="break-all font-mono text-xs text-foreground">{{ maskUrl(form.database_url) }}</p>
      <Badge v-if="probe.db.dialect" variant="outline">{{ probe.db.dialect }}</Badge>
    </Card>

    <Card class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">管理员</span>
        <button class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary" @click="emit('edit', 1)"><Pencil class="h-3 w-3" />修改</button>
      </div>
      <p class="text-xs text-foreground">{{ form.admin.username }}<span v-if="form.admin.display_name" class="text-muted-foreground"> · {{ form.admin.display_name }}</span></p>
      <p v-if="form.admin.email" class="text-xs text-muted-foreground">{{ form.admin.email }}</p>
      <p class="text-xs text-muted-foreground">密码：••••••••</p>
    </Card>

    <Card class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">人工智能</span>
        <button class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary" @click="emit('edit', 2)"><Pencil class="h-3 w-3" />修改</button>
      </div>
      <template v-if="aiSkipped">
        <p class="text-xs text-muted-foreground">暂不配置（可稍后在设置页启用）</p>
      </template>
      <template v-else-if="ai">
        <p class="text-xs text-foreground">{{ ai.id }} · {{ ai.model || '（未选模型）' }}</p>
        <p class="break-all text-xs text-muted-foreground">{{ ai.base_url }}</p>
        <p class="text-xs text-muted-foreground">密钥：{{ ai.api_key ? '••••（已填写）' : '（空）' }}</p>
      </template>
    </Card>

    <Card class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">地图</span>
        <button class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary" @click="emit('edit', 3)"><Pencil class="h-3 w-3" />修改</button>
      </div>
      <p class="text-xs text-foreground">默认底图：{{ mapLabel }}</p>
      <p class="text-xs text-muted-foreground">密钥：{{ map?.key ? '••••（已填写）' : '（留空 / 免密钥）' }}</p>
    </Card>

    <Card class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">邮件通知</span>
        <button class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary" @click="emit('edit', 4)"><Pencil class="h-3 w-3" />修改</button>
      </div>
      <p class="text-xs text-foreground">邮件：{{ form.mail_skipped ? '已跳过' : '已配置' }}</p>
      <p v-if="form.mail_skipped" class="text-xs text-muted-foreground">安装完成后可在设置页补充。</p>
      <template v-else-if="form.mail">
        <p class="text-xs text-muted-foreground">{{ form.mail.host }} · {{ form.mail.from_addr }}</p>
        <p class="text-xs text-muted-foreground">密钥：{{ form.mail.password ? '••••（已填写）' : '（留空）' }}</p>
      </template>
    </Card>

    <Card class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium">安全 / 运行时</span>
        <button class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary" @click="emit('edit', 5)"><Pencil class="h-3 w-3" />修改</button>
      </div>
      <p class="text-xs text-muted-foreground">主密钥：••••••••（{{ probe.secretBackedUp ? '已下载备份' : '未备份' }}）</p>
      <p class="text-xs text-muted-foreground">Redis：{{ form.redis_enabled ? '已启用' : '未启用（进程内事件总线）' }}</p>
      <p class="text-xs text-muted-foreground">AI 写工具：{{ form.ai_tools_enabled ? '启用' : '关闭' }}</p>
    </Card>
  </div>
</template>
