<script setup lang="ts">
/** 二次确认对话框：基于 ui/Dialog，含取消 / 确认。 */
import Dialog from '@/components/ui/Dialog.vue'
import Button from '@/components/ui/Button.vue'

const open = defineModel<boolean>({ default: false })
withDefaults(
  defineProps<{
    title?: string
    message?: string
    confirmText?: string
    cancelText?: string
    danger?: boolean
    busy?: boolean
  }>(),
  {
    title: '确认操作',
    message: '确定要继续吗？',
    confirmText: '确定',
    cancelText: '取消',
    danger: false,
    busy: false,
  },
)
const emit = defineEmits<{ confirm: [] }>()

function onConfirm() {
  emit('confirm')
}
</script>

<template>
  <Dialog v-model="open" :title="title" width="max-w-sm">
    <p class="text-sm leading-relaxed text-muted-foreground">{{ message }}</p>
    <template #footer>
      <Button variant="outline" size="sm" :disabled="busy" @click="open = false">{{ cancelText }}</Button>
      <Button size="sm" :variant="danger ? 'destructive' : 'default'" :disabled="busy" @click="onConfirm">
        {{ busy ? '处理中…' : confirmText }}
      </Button>
    </template>
  </Dialog>
</template>
