<script setup lang="ts">
/** 第 2 步：管理员账号。argon2 由后端处理；密码至少 8 位且两次一致。 */
import { computed } from 'vue'
import { UserRound } from 'lucide-vue-next'
import Input from '@/components/ui/Input.vue'
import type { InstallIn, WizardProbe } from '@/stores/config'

const props = defineProps<{ form: InstallIn; probe: WizardProbe }>()

const passwordOk = computed(() => props.form.admin.password.length >= 8)
const confirmOk = computed(() => props.form.admin.password === props.probe.adminConfirm)
// email / phone 允许 null；用字符串代理，空串回写为 null
const email = computed({
  get: () => props.form.admin.email ?? '',
  set: (v: string) => { props.form.admin.email = v.trim() || null },
})
const phone = computed({
  get: () => props.form.admin.phone ?? '',
  set: (v: string) => { props.form.admin.phone = v.trim() || null },
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <UserRound class="mt-0.5 h-4 w-4 shrink-0" />
      <span>创建初始 owner 账号。密码经 argon2 哈希存库，明文不出浏览器；安装完成后用此账号登录。</span>
    </div>

    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="space-y-1.5">
        <label class="text-xs font-medium">用户名 <span class="text-destructive">*</span></label>
        <Input v-model="form.admin.username" placeholder="admin" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">显示名称</label>
        <Input v-model="form.admin.display_name" placeholder="可选" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">密码 <span class="text-destructive">*</span></label>
        <Input v-model="form.admin.password" type="password" placeholder="至少 8 位" :invalid="!passwordOk && form.admin.password.length > 0" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">确认密码 <span class="text-destructive">*</span></label>
        <Input v-model="probe.adminConfirm" type="password" placeholder="再次输入" :invalid="!confirmOk && probe.adminConfirm.length > 0" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">邮箱</label>
        <Input v-model="email" placeholder="可选" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">手机号</label>
        <Input v-model="phone" placeholder="可选" />
      </div>
    </div>

    <p v-if="!passwordOk && form.admin.password.length > 0" class="text-xs text-destructive">密码至少需要 8 位。</p>
    <p v-else-if="!confirmOk && probe.adminConfirm.length > 0" class="text-xs text-destructive">两次输入的密码不一致。</p>
    <p v-else class="text-xs text-muted-foreground">带 * 为必填项。</p>
  </div>
</template>
