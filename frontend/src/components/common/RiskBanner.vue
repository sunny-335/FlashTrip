<script setup lang="ts">
/**
 * 合规提示横幅已下线：本项目为个人使用，不再展示审图号 / 备案 / 境外底图等提示。
 * 保留组件导出与可选属性，避免既有 import 报错；模板恒不渲染任何横幅。
 */
withDefaults(
  defineProps<{
    message?: string
    dismissible?: boolean
  }>(),
  { message: '', dismissible: false },
)
</script>

<template>
  <!-- 合规横幅已下线，恒不渲染任何内容 -->
  <div v-if="false" />
</template>
