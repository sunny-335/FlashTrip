<script setup lang="ts">
/** Markdown 安全渲染：markdown-it 解析 + DOMPurify 消毒，用于 AI 回复与出行建议等内容。 */
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const props = withDefaults(
  defineProps<{
    /** Markdown 原文；空值渲染为空。 */
    source?: string | null
    /** 紧凑排版（列表与段落间距更小）。 */
    compact?: boolean
  }>(),
  { source: '', compact: false },
)

const md = new MarkdownIt({ breaks: true, linkify: true, html: false })

const html = computed(() => {
  const text = (props.source ?? '').trim()
  if (!text) return ''
  const raw = md.render(text)
  // 允许链接与图片，过滤脚本、事件与危险协议
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
})
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html —— 内容已经 DOMPurify 消毒 -->
  <div
    class="markdown-body text-sm leading-relaxed text-foreground"
    :class="compact ? 'space-y-1.5' : 'space-y-3'"
    v-html="html"
  />
</template>

<style scoped>
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin-top: 0.75em;
  font-weight: 600;
  line-height: 1.4;
}
.markdown-body :deep(h1) { font-size: 1.15em; }
.markdown-body :deep(h2) { font-size: 1.1em; }
.markdown-body :deep(h3),
.markdown-body :deep(h4) { font-size: 1.05em; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.4em;
}
.markdown-body :deep(ul) { list-style: disc; }
.markdown-body :deep(ol) { list-style: decimal; }
.markdown-body :deep(li) { margin: 0.2em 0; }
.markdown-body :deep(li > p) { margin: 0; }
.markdown-body :deep(a) {
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-all;
}
.markdown-body :deep(code) {
  padding: 0.1em 0.35em;
  border-radius: 0.25rem;
  background: var(--muted);
  font-size: 0.9em;
}
.markdown-body :deep(pre) {
  padding: 0.75rem;
  border-radius: 0.5rem;
  background: var(--muted);
  overflow-x: auto;
}
.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
}
.markdown-body :deep(blockquote) {
  padding-left: 0.75em;
  border-left: 3px solid var(--border);
  color: var(--muted-foreground);
}
.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 0.3em 0.6em;
  border: 1px solid var(--border);
  text-align: left;
}
.markdown-body :deep(hr) {
  margin: 1em 0;
  border-color: var(--border);
}
.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: 0.5rem;
}
</style>
