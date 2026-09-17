import { afterEach, describe, expect, it, vi } from 'vitest';
import { chatApi } from '../api/chat';
import type {
  ChatInput,
  ChatResponse,
  ChatRunState,
  ChatStreamEvent,
  ChatStreamEventType,
} from '../types/api';

const encoder = new TextEncoder();
const timestamp = '2026-08-19T10:00:00Z';

const input: ChatInput = {
  conversation_id: 'conversation-1',
  content: '华东销售额是多少？',
  client_message_id: 'client-message-1',
  attachment_ids: [],
};

function response(content: string): ChatResponse {
  const conversation = {
    id: 'conversation-1', title: '华东销售分析', summary: '', active_attachment_ids: [], created_at: timestamp, updated_at: timestamp,
  };
  return {
    conversation,
    user_message: {
      id: 'user-1', conversation_id: conversation.id, role: 'user', content: input.content, status: 'COMPLETED',
      attachment_ids: [], response_payload: {}, trace_payload: {}, created_at: timestamp,
    },
    assistant_message: {
      id: 'assistant-1', conversation_id: conversation.id, role: 'assistant', content, status: 'SUCCEEDED',
      attachment_ids: [], response_payload: {}, trace_payload: {}, created_at: timestamp,
    },
  };
}

function event<T extends ChatStreamEventType>(eventType: T, seq: number, fields: Record<string, unknown> = {}) {
  return {
    seq,
    run_id: 'run-1',
    conversation_id: input.conversation_id,
    message_id: `pending-${input.client_message_id}`,
    timestamp,
    event_type: eventType,
    ...fields,
  };
}

function sse(eventName: string, payload: unknown, multiline = false): string {
  const json = JSON.stringify(payload, null, multiline ? 2 : 0);
  const data = multiline ? json.split('\n').map((line) => `data: ${line}`).join('\r\n') : `data: ${json}`;
  return `event: ${eventName}\r\n${data}\r\n\r\n`;
}

function byteChunks(source: string, cutPoints: number[] = []): Uint8Array[] {
  const bytes = encoder.encode(source);
  const points = [...cutPoints.filter((point) => point > 0 && point < bytes.length), bytes.length];
  const chunks: Uint8Array[] = [];
  let start = 0;
  for (const end of points) {
    chunks.push(bytes.slice(start, end));
    start = end;
  }
  return chunks;
}

function mockStream(chunks: Uint8Array[], status = 200): ReturnType<typeof vi.fn> {
  let index = 0;
  const cancel = vi.fn().mockResolvedValue(undefined);
  const read = vi.fn(async () => index < chunks.length
    ? { done: false as const, value: chunks[index++] }
    : { done: true as const, value: undefined });
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    body: { getReader: () => ({ read, cancel }) },
    text: vi.fn().mockResolvedValue(''),
  } as unknown as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('chatApi.stream canonical SSE', () => {
  it('parses split chunks and multiline data, batches real deltas, and returns the final response', async () => {
    const final = response('华东销售额为 128 万元。');
    const source = [
      sse('run.started', event('run.started', 1)),
      sse('phase.started', event('phase.started', 2, {
        phase: 'querying_data', label: '正在查询数据……', metadata: {},
      }), true),
      sse('answer.delta', event('answer.delta', 3, { delta: '华东销售额为 ' })),
      sse('answer.delta', event('answer.delta', 4, { delta: '128 万元。' })),
      sse('run.completed', event('run.completed', 5, {
        status: 'SUCCEEDED', result_semantic: 'VALUE', message_parts: [{ type: 'text', text: final.assistant_message.content }], response: final,
      })),
    ].join('');
    mockStream(byteChunks(source, [1, 7, 38, 103, 151, 207, 319, 401]));
    const events: ChatStreamEvent[] = [];
    const deltas: string[] = [];
    const states: ChatRunState[] = [];

    const result = await chatApi.stream(input, {
      onEvent: (value) => events.push(value),
      onDelta: (delta) => deltas.push(delta),
      onStateChange: (state) => states.push(state),
    }, new AbortController().signal);

    expect(result).toEqual(final);
    expect(deltas).toEqual(['华东销售额为 128 万元。']);
    expect(events.map((value) => value.event_type)).toEqual([
      'run.started', 'phase.started', 'answer.delta', 'answer.delta', 'run.completed',
    ]);
    expect(states).toEqual(['SUBMITTING', 'RUNNING', 'STREAMING', 'COMPLETED']);
  });

  it('deduplicates and rejects out-of-order seq values and ignores business events after the unique terminal', async () => {
    const final = response('AC');
    const source = [
      sse('run.started', event('run.started', 1)),
      sse('answer.delta', event('answer.delta', 3, { delta: 'A' })),
      sse('answer.delta', event('answer.delta', 3, { delta: 'duplicate' })),
      sse('answer.delta', event('answer.delta', 2, { delta: 'out-of-order' })),
      sse('answer.delta', event('answer.delta', 4, { delta: 'C' })),
      sse('run.completed', event('run.completed', 5, {
        status: 'SUCCEEDED', result_semantic: 'VALUE', message_parts: [], response: final,
      })),
      sse('answer.delta', event('answer.delta', 6, { delta: 'late' })),
      sse('run.failed', event('run.failed', 7, { code: 'LATE_FAILURE', message: 'late', retryable: false })),
    ].join('');
    mockStream(byteChunks(source));
    const eventTypes: string[] = [];
    const deltas: string[] = [];

    await expect(chatApi.stream(input, {
      onEvent: (value) => eventTypes.push(value.event_type),
      onDelta: (delta) => deltas.push(delta),
    }, new AbortController().signal)).resolves.toEqual(final);

    expect(deltas).toEqual(['AC']);
    expect(eventTypes).toEqual(['run.started', 'answer.delta', 'answer.delta', 'run.completed']);
    expect(eventTypes.filter((value) => value.startsWith('run.'))).toEqual(['run.started', 'run.completed']);
  });

  it('flushes buffered delta before run.failed and exposes the normative error code', async () => {
    const source = [
      sse('run.started', event('run.started', 1)),
      sse('answer.delta', event('answer.delta', 2, { delta: 'partial' })),
      sse('run.failed', event('run.failed', 3, { code: 'QUERY_TIMEOUT', message: '查询超时', retryable: true })),
    ].join('');
    mockStream(byteChunks(source));
    const order: string[] = [];
    const states: ChatRunState[] = [];

    const promise = chatApi.stream(input, {
      onDelta: (delta) => order.push(`delta:${delta}`),
      onEvent: (value) => { if (value.event_type === 'run.failed') order.push(`failed:${value.code}`); },
      onStateChange: (state) => states.push(state),
    }, new AbortController().signal);

    await expect(promise).rejects.toMatchObject({
      name: 'ChatStreamError', code: 'QUERY_TIMEOUT', retryable: true,
    });
    expect(order).toEqual(['delta:partial', 'failed:QUERY_TIMEOUT']);
    expect(states.at(-1)).toBe('FAILED');
  });

  it('handles an authorization failure carried by normative run.failed fields', async () => {
    const source = [
      sse('run.started', event('run.started', 1)),
      sse('run.failed', event('run.failed', 2, {
        code: 'HTTP_401', message: '登录状态已失效', retryable: false,
      })),
    ].join('');
    mockStream(byteChunks(source));
    const unauthorized = vi.fn();
    window.addEventListener('chatbi:unauthorized', unauthorized, { once: true });

    await expect(chatApi.stream(input, {}, new AbortController().signal)).rejects.toMatchObject({
      name: 'Error', status: 401, message: '登录状态已失效',
    });
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it('treats run.cancelled as AbortError and never transitions it to FAILED', async () => {
    const source = [
      sse('run.started', event('run.started', 1)),
      sse('answer.delta', event('answer.delta', 2, { delta: 'partial' })),
      sse('run.cancelled', event('run.cancelled', 3, { code: 'RUN_CANCELLED', message: '用户停止生成' })),
    ].join('');
    mockStream(byteChunks(source));
    const states: ChatRunState[] = [];
    const deltas: string[] = [];

    await expect(chatApi.stream(input, {
      onDelta: (delta) => deltas.push(delta),
      onStateChange: (state) => states.push(state),
    }, new AbortController().signal)).rejects.toMatchObject({ name: 'AbortError' });

    expect(deltas).toEqual(['partial']);
    expect(states.at(-1)).toBe('CANCELLED');
    expect(states).not.toContain('FAILED');
  });

  it('fails closed when final persisted content differs from concatenated deltas', async () => {
    const final = response('different');
    const source = [
      sse('run.started', event('run.started', 1)),
      sse('answer.delta', event('answer.delta', 2, { delta: 'streamed' })),
      sse('run.completed', event('run.completed', 3, {
        status: 'SUCCEEDED', result_semantic: 'VALUE', message_parts: [], response: final,
      })),
    ].join('');
    mockStream(byteChunks(source));

    await expect(chatApi.stream(input, {}, new AbortController().signal)).rejects.toMatchObject({
      name: 'ChatStreamProtocolError', code: 'FINAL_RESPONSE_MISMATCH',
    });
  });

  it('rejects malformed JSON and handles an HTML 401 response without evaluating the body', async () => {
    mockStream(byteChunks('event: run.started\ndata: {not-json}\n\n'));
    await expect(chatApi.stream(input, {}, new AbortController().signal)).rejects.toMatchObject({
      code: 'INVALID_SSE_JSON',
    });

    const unauthorized = vi.fn();
    window.addEventListener('chatbi:unauthorized', unauthorized, { once: true });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: vi.fn().mockResolvedValue('<script>window.__unsafeExecuted = true</script>'),
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await expect(chatApi.stream(input, {}, new AbortController().signal)).rejects.toMatchObject({
      status: 401, message: '请求失败 (401)',
    });
    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect((window as unknown as Record<string, unknown>).__unsafeExecuted).toBeUndefined();
  });

  it('cancels and releases the response reader when protocol validation fails', async () => {
    const chunks = byteChunks('event: run.started\ndata: {not-json}\n\n');
    const cancel = vi.fn().mockResolvedValue(undefined);
    const releaseLock = vi.fn();
    let index = 0;
    const read = vi.fn(async () => index < chunks.length
      ? { done: false as const, value: chunks[index++] }
      : { done: true as const, value: undefined });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: { getReader: () => ({ read, cancel, releaseLock }) },
    } as unknown as Response));

    await expect(chatApi.stream(input, {}, new AbortController().signal)).rejects.toMatchObject({
      code: 'INVALID_SSE_JSON',
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(releaseLock).toHaveBeenCalledTimes(1);
  });

  it('keeps the old accepted/answer_delta/result protocol as an internal fallback', async () => {
    const final = response('legacy answer');
    const legacy = [
      sse('accepted', { trace_id: 'legacy-run', sequence: 1, timestamp, event: 'accepted', data: { conversation_id: input.conversation_id } }),
      sse('answer_delta', { trace_id: 'legacy-run', sequence: 2, timestamp, event: 'answer_delta', data: { text: 'legacy answer' } }),
      sse('completed', { trace_id: 'legacy-run', sequence: 3, timestamp, event: 'completed', data: {} }),
      sse('result', final),
    ].join('');
    mockStream(byteChunks(legacy));
    const exposed: string[] = [];

    await expect(chatApi.stream(input, {
      onEvent: (value) => exposed.push(value.event_type),
    }, new AbortController().signal)).resolves.toEqual(final);

    expect(exposed).toEqual(['run.started', 'answer.delta', 'run.completed']);
  });
});

describe('chatApi.upload', () => {
  it('safely rejects non-JSON upload errors while preserving progress and credentials', async () => {
    let request: FakeXhr | undefined;
    class FakeXhr {
      upload: { onprogress?: (event: ProgressEvent) => void } = {};
      withCredentials = false;
      status = 500;
      responseText = '<img src=x onerror="window.__unsafeExecuted=true">';
      onload?: () => void;
      onerror?: () => void;
      onabort?: () => void;
      open = vi.fn();
      send = vi.fn(() => {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 } as ProgressEvent);
        this.onload?.();
      });
      constructor() { request = this; }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    const progress = vi.fn();

    await expect(chatApi.upload('conversation-1', new File(['x'], 'unsafe.html'), progress)).rejects.toMatchObject({
      status: 500, message: '上传失败 (500)',
    });
    expect(progress).toHaveBeenCalledWith(50);
    expect(request?.withCredentials).toBe(true);
    expect((window as unknown as Record<string, unknown>).__unsafeExecuted).toBeUndefined();
  });
});
