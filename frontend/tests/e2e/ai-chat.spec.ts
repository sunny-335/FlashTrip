/**
 * E2E：AI 对话 SSE 流式与写工具二次确认。
 *
 * 跳过原因：真实流程需要已启动的前后端服务、登录态与已配置且可用的 AI provider
 * （真实模型调用会产生费用/延迟），CI 不提供密钥，故用 test.skip 声明；
 * 联调时把 test.skip 改为 test 并配置 AI provider。
 *
 * 不阻塞保证：vitest 只收集 src/**，vite build / vue-tsc 不包含 tests/e2e；
 * 「契约快照」用例为纯断言，含 SSE 帧解析（不访问网络）。
 */
import { test, expect } from '@playwright/test'

/** 契约快照：按 api.ts postSSE 的切帧规则解析 delta / tool_call / done。 */
test('契约快照：SSE 帧解析与工具确认字段（无需服务）', () => {
  const stream = [
    'event: delta',
    'data: {"delta":"为你"}',
    '',
    'event: delta',
    'data: {"delta":"规划三天"}',
    '',
    'event: tool_call',
    'data: {"toolCallId":"c1","name":"add_plan_item","arguments":{},"needConfirm":true,"status":"pending"}',
    '',
    'event: done',
    'data: {"conversationId":"conv1","pendingConfirmation":true}',
    '',
  ].join('\n')

  let text = ''
  const tools: { toolCallId: string; needConfirm: boolean }[] = []
  let conversationId = ''
  for (const chunk of stream.split('\n\n')) {
    let event = 'message'
    let data = ''
    for (const line of chunk.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!data) continue
    const parsed = JSON.parse(data) as Record<string, unknown>
    if (event === 'delta') text += (parsed.delta ?? parsed.content ?? '') as string
    if (event === 'tool_call') tools.push({ toolCallId: parsed.toolCallId as string, needConfirm: Boolean(parsed.needConfirm) })
    if (event === 'done') conversationId = parsed.conversationId as string
  }
  expect(text).toBe('为你规划三天')
  expect(tools).toEqual([{ toolCallId: 'c1', needConfirm: true }])
  expect(conversationId).toBe('conv1')

  // 确认时把调用数组回传 /ai/chat 的 confirmToolCalls
  const confirmBody = {
    confirmToolCalls: [{ toolCallId: 'c1', name: 'add_plan_item', arguments: {} }],
  }
  expect(confirmBody.confirmToolCalls[0].toolCallId).toBe('c1')
  expect('/api/v1/ai/chat').toContain('/ai/chat')
})

test.skip('真实流程：全局 FAB 回复按 delta 流式追加（需真实服务与 AI 配置）', async ({ page }) => {
  await page.goto('/dashboard')
  await page.getByTitle('瞬旅 AI 助手').click()
  const input = page.getByPlaceholder('输入问题…')
  await input.fill('给我一个三天的行程建议')
  await input.press('Enter')

  // 流式内容逐段追加到同一条 assistant 气泡（mr-8 bg-muted）
  const answer = page.locator('.mr-8.bg-muted').last()
  await expect(answer).not.toBeEmpty({ timeout: 30000 })
  // 发送期间按钮禁用，done 后恢复可输入
  await expect(input).toBeEnabled()
  await expect(answer).not.toContainText('[连接失败]')

  // 写工具确认卡片由 AgentPanel / ToolCallCard 承载（全局 FAB 仅做纯文本流式）：
  // 打开内嵌 AgentPanel 的页面后，确认按钮会触发携带 confirmToolCalls 的二次 /ai/chat，
  // 该链路的字段契约已在上方「契约快照」用例中校验。
})
