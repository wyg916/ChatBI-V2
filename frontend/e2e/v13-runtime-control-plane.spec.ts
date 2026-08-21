import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';


async function createConversation(request: APIRequestContext, title: string) {
  const response = await request.post('/api/v1/conversations', { data: { title } });
  expect(response.status()).toBe(201);
  return response.json();
}


test('date question uses L0 MODEL=NONE and persists the governed trace', async ({ request }) => {
  const conversation = await createConversation(request, 'V1.3 Date L0');
  const response = await request.post('/api/v1/chat', {
    data: {
      conversation_id: conversation.id,
      client_message_id: 'e2e-v13-date-model-none-001',
      content: '今天是几号？',
    },
  });
  expect(response.status()).toBe(201);
  const payload = await response.json();
  const trace = payload.assistant_message.trace_payload;
  expect(payload.assistant_message.content).toContain('当前日期是');
  expect(trace.model_provider).toBe('none');
  expect(trace.model_name).toBe('none');
  expect(trace.router_decision.requested_alias).toBe('none');
  expect(trace.router_decision.model_required).toBe(false);
  expect(trace.request_id).toBe('e2e-v13-date-model-none-001');
  expect(trace.trace_id).toMatch(/^TRACE-/);
});


test('canonical SSE binds trace request conversation and message identities', async ({ request }) => {
  const conversation = await createConversation(request, 'V1.3 SSE identity');
  const clientMessageId = 'e2e-v13-sse-identity-001';
  const response = await request.post('/api/v1/chat/stream', {
    data: {
      conversation_id: conversation.id,
      client_message_id: clientMessageId,
      content: '今天星期几？',
    },
    timeout: 30_000,
  });
  expect(response.status()).toBe(200);
  const events = (await response.text())
    .split('\n\n')
    .map((block) => block.split('\n').find((line) => line.startsWith('data: ')))
    .filter((line): line is string => Boolean(line))
    .map((line) => JSON.parse(line.slice(6)));
  expect(events.length).toBeGreaterThan(2);
  expect(events.at(0)?.event_type).toBe('run.started');
  expect(events.at(-1)?.event_type).toBe('run.completed');
  expect(new Set(events.map((item) => item.trace_id)).size).toBe(1);
  expect(events.every((item) => item.trace_id === item.run_id)).toBe(true);
  expect(events.every((item) => item.request_id === clientMessageId)).toBe(true);
  expect(events.every((item) => item.message_id === clientMessageId)).toBe(true);
  expect(events.every((item) => item.conversation_id === conversation.id)).toBe(true);
  const persistedTrace = events.at(-1)?.response?.assistant_message?.trace_payload?.trace_id;
  expect(persistedTrace).toBe(events.at(-1)?.trace_id);
});


test('two conversations never bind the other conversation response', async ({ request }) => {
  const left = await createConversation(request, 'V1.3 left');
  const right = await createConversation(request, 'V1.3 right');
  for (const [conversationId, clientMessageId] of [
    [left.id, 'e2e-v13-left-message-001'],
    [right.id, 'e2e-v13-right-message-001'],
  ]) {
    const response = await request.post('/api/v1/chat', {
      data: { conversation_id: conversationId, client_message_id: clientMessageId, content: '今天是几号？' },
    });
    expect(response.status()).toBe(201);
  }
  const leftDetail = await (await request.get(`/api/v1/conversations/${left.id}`)).json();
  const rightDetail = await (await request.get(`/api/v1/conversations/${right.id}`)).json();
  expect(leftDetail.messages).toHaveLength(2);
  expect(rightDetail.messages).toHaveLength(2);
  expect(leftDetail.messages.every((item: { conversation_id: string }) => item.conversation_id === left.id)).toBe(true);
  expect(rightDetail.messages.every((item: { conversation_id: string }) => item.conversation_id === right.id)).toBe(true);
  expect(new Set([...leftDetail.messages, ...rightDetail.messages].map((item: { id: string }) => item.id)).size).toBe(4);
});
