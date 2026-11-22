<script setup lang="ts">
/**
 * 第 2 步：管理员账号。密码强度由 PasswordStrength 实时评估，
 * 未达到管理员标准（8–32 位、四类字符齐全、无连续串）时禁用「下一步」并显示中文原因。
 */
import { computed } from 'vue'
import { UserRound } from 'lucide-vue-next'
import Input from '@/components/ui/Input.vue'
import PasswordStrength from '@/components/settings/PasswordStrength.vue'
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

function onStrength(info: { meetsPolicy: boolean }) {
  props.probe.adminMeetsPolicy = info.meetsPolicy
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
      <UserRound class="mt-0.5 h-4 w-4 shrink-0" />
      <span>创建初始管理员账号。密码经 argon2 哈希存库，明文不出浏览器；安装完成后用此账号登录。</span>
    </div>

    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="space-y-1.5">
        <label class="text-xs font-medium">用户名 <span class="text-destructive">*</span></label>
        <Input v-model="form.admin.username" placeholder="管理员用户名" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">显示名称</label>
        <Input v-model="form.admin.display_name" placeholder="可选" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-medium">密码 <span class="text-destructive">*</span></label>
        <Input v-model="form.admin.password" type="password" placeholder="8–32 位，含四类字符" :invalid="!passwordOk && form.admin.password.length > 0" />
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

    <PasswordStrength :password="form.admin.password" is-admin @change="onStrength" />

    <p v-if="!passwordOk && form.admin.password.length > 0" class="text-xs text-destructive">密码至少需要 8 位。</p>
    <p v-else-if="!confirmOk && probe.adminConfirm.length > 0" class="text-xs text-destructive">两次输入的密码不一致。</p>
    <p v-else-if="!probe.adminMeetsPolicy && form.admin.password" class="text-xs text-destructive">
      管理员密码须为 8–32 位，且同时包含大写字母、小写字母、数字与特殊字符，并避开连续或重复字符串；达标后才能继续。
    </p>
    <p v-else class="text-xs text-muted-foreground">带 * 为必填项；密码强度达到管理员标准后方可进入下一步。</p>
  </div>
</template>
