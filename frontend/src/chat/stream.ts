import { API_BASE, ApiError } from '../api/client';
import type {
  ChatInput,
  ChatPublicPhase,
  ChatResponse,
  ChatRunCompletedEvent,
  ChatRunState,
  ChatStreamEvent,
  ChatStreamEventType,
  ChatStreamHandlers,
  MessagePart,
  ResultSemantic,
} from '../types/api';

type JsonRecord = Record<string, unknown>;

interface SseFrame {
  event: string;
  data: string;
}

const CANONICAL_EVENTS = new Set<ChatStreamEventType>([
  'run.started',
  'phase.started',
  'phase.completed',
  'answer.delta',
  'artifact.ready',
  'citations.ready',
  'run.completed',
  'run.failed',
  'run.cancelled',
  'heartbeat',
]);

const PUBLIC_PHASES = new Set<ChatPublicPhase>([
  'understanding',
  'semantic_mapping',
  'querying_data',
  'retrieving_knowledge',
  'verifying',
  'composing_answer',
]);

const RESULT_SEMANTICS = new Set<ResultSemantic>(['VALUE', 'ZERO', 'NO_ROWS', 'NULL_VALUE', 'FAILED']);

const LEGACY_PHASES: Record<string, ChatPublicPhase> = {
  progress: 'understanding',
  catalog_retrieving: 'understanding',
  schema_linked: 'semantic_mapping',
  semantic_parsing: 'semantic_mapping',
  semantic_compiling: 'semantic_mapping',
  sql_validating: 'querying_data',
  sql_running: 'querying_data',
  result_validating: 'verifying',
  knowledge_retrieving: 'retrieving_knowledge',
  agent_running: 'understanding',
  python_running: 'querying_data',
};

const PHASE_LABELS: Record<ChatPublicPhase, string> = {
  understanding: '正在理解问题……',
  semantic_mapping: '正在识别指标和维度……',
  querying_data: '正在查询数据……',
  retrieving_knowledge: '正在检索业务规则……',
  verifying: '正在校验结果……',
  composing_answer: '正在整理回答……',
};

export class ChatStreamProtocolError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'ChatStreamProtocolError';
    this.code = code;
  }
}

export class ChatStreamError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(code: string, message: string, retryable: boolean) {
    super(message);
    this.name = 'ChatStreamError';
    this.code = code;
    this.retryable = retryable;
  }
}

class SseDecoder {
  private buffer = '';
  private eventName = '';
  private dataLines: string[] = [];
  private firstLine = true;

  feed(chunk: string): SseFrame[] {
    this.buffer += chunk;
    return this.consumeLines(false);
  }

  end(chunk = ''): SseFrame[] {
    this.buffer += chunk;
    const frames = this.consumeLines(true);
    if (this.buffer.length > 0) {
      this.processLine(this.buffer, frames);
      this.buffer = '';
    }
    this.dispatch(frames);
    return frames;
  }

  private consumeLines(final: boolean): SseFrame[] {
    const frames: SseFrame[] = [];
    while (this.buffer.length > 0) {
      const match = /[\r\n]/.exec(this.buffer);
      if (!match) break;
      const index = match.index;
      if (!final && this.buffer[index] === '\r' && index === this.buffer.length - 1) break;
      const newlineLength = this.buffer[index] === '\r' && this.buffer[index + 1] === '\n' ? 2 : 1;
      const line = this.buffer.slice(0, index);
      this.buffer = this.buffer.slice(index + newlineLength);
      this.processLine(line, frames);
    }
    return frames;
  }

  private processLine(source: string, frames: SseFrame[]): void {
    let line = source;
    if (this.firstLine) {
      this.firstLine = false;
      line = line.replace(/^\uFEFF/, '');
    }
    if (line === '') {
      this.dispatch(frames);
      return;
    }
    if (line.startsWith(':')) return;
    const separator = line.indexOf(':');
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? '' : line.slice(separator + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') this.eventName = value;
    if (field === 'data') this.dataLines.push(value);
  }

  private dispatch(frames: SseFrame[]): void {
    if (this.dataLines.length > 0) {
      frames.push({ event: this.eventName || 'message', data: this.dataLines.join('\n') });
    }
    this.eventName = '';
    this.dataLines = [];
  }
}

class DeltaBatcher {
  private pending = '';
  private latestEvent: ChatStreamEvent | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly callback?: ChatStreamHandlers['onDelta']) {}

  append(delta: string, event: ChatStreamEvent): void {
    this.pending += delta;
    this.latestEvent = event;
    if (!this.timer) this.timer = setTimeout(() => this.flush(), 40);
  }

  flush(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    if (!this.pending || !this.latestEvent) return;
    const pending = this.pending;
    const event = this.latestEvent;
    this.pending = '';
    this.latestEvent = undefined;
    this.callback?.(pending, event);
  }
}

interface LegacyContext {
  runId: string;
  conversationId: string;
  messageId: string;
  nextSeq: number;
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown): JsonRecord {
  return isRecord(value) ? value : {};
}

function requiredRecord(value: unknown, label: string): JsonRecord {
  if (!isRecord(value)) throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', `${label} 必须是对象`);
  return value;
}

function requiredString(payload: JsonRecord, field: string): string {
  const value = payload[field];
  if (typeof value !== 'string' || value.length === 0) {
    throw new ChatStreamProtocolError('INVALID_EVENT_ENVELOPE', `流式事件缺少 ${field}`);
  }
  return value;
}

function requiredBoolean(payload: JsonRecord, field: string): boolean {
  const value = payload[field];
  if (typeof value !== 'boolean') {
    throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', `流式事件缺少 ${field}`);
  }
  return value;
}

function parseJson(data: string): JsonRecord {
  try {
    return requiredRecord(JSON.parse(data) as unknown, 'SSE data');
  } catch (error) {
    if (error instanceof ChatStreamProtocolError) throw error;
    throw new ChatStreamProtocolError('INVALID_SSE_JSON', '流式事件包含无效 JSON');
  }
}

function validateResponse(value: unknown): ChatResponse {
  const response = requiredRecord(value, 'run.completed.response');
  requiredRecord(response.conversation, 'run.completed.response.conversation');
  requiredRecord(response.user_message, 'run.completed.response.user_message');
  const assistant = requiredRecord(response.assistant_message, 'run.completed.response.assistant_message');
  requiredString(assistant, 'content');
  return response as unknown as ChatResponse;
}

function validateCanonical(frame: SseFrame, payload: JsonRecord): ChatStreamEvent {
  const eventType = requiredString(payload, 'event_type');
  if (!CANONICAL_EVENTS.has(eventType as ChatStreamEventType)) {
    throw new ChatStreamProtocolError('UNKNOWN_EVENT_TYPE', `不支持的流式事件 ${eventType}`);
  }
  if (frame.event !== eventType) {
    throw new ChatStreamProtocolError('EVENT_TYPE_MISMATCH', 'SSE event 与 event_type 不一致');
  }
  const seq = payload.seq;
  if (!Number.isInteger(seq) || Number(seq) < 1) {
    throw new ChatStreamProtocolError('INVALID_EVENT_ENVELOPE', '流式事件 seq 必须是正整数');
  }
  requiredString(payload, 'run_id');
  requiredString(payload, 'conversation_id');
  requiredString(payload, 'message_id');
  requiredString(payload, 'timestamp');

  if (eventType === 'phase.started' || eventType === 'phase.completed') {
    const phase = requiredString(payload, 'phase');
    if (!PUBLIC_PHASES.has(phase as ChatPublicPhase)) {
      throw new ChatStreamProtocolError('INVALID_PUBLIC_PHASE', `不支持的公开阶段 ${phase}`);
    }
    requiredString(payload, 'label');
    if (payload.duration_ms !== undefined && (typeof payload.duration_ms !== 'number' || payload.duration_ms < 0)) {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', 'duration_ms 必须是非负数');
    }
    if (payload.metadata !== undefined && !isRecord(payload.metadata)) {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', 'metadata 必须是对象');
    }
  } else if (eventType === 'answer.delta') {
    requiredString(payload, 'delta');
  } else if (eventType === 'artifact.ready') {
    requiredString(payload, 'artifact_type');
    requiredRecord(payload.artifact, 'artifact.ready.artifact');
  } else if (eventType === 'citations.ready') {
    if (!Array.isArray(payload.citations)) {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', 'citations.ready.citations 必须是数组');
    }
    for (const value of payload.citations) {
      const citation = requiredRecord(value, 'citation');
      requiredString(citation, 'title');
      if ((typeof citation.version !== 'string' || citation.version.length === 0) && typeof citation.version !== 'number') {
        throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', 'citation 缺少 version');
      }
      requiredString(citation, 'locator');
      requiredString(citation, 'resource_id');
    }
  } else if (eventType === 'run.completed') {
    const status = requiredString(payload, 'status');
    if (status !== 'SUCCEEDED' && status !== 'PARTIAL') {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', `run.completed.status 不受支持: ${status}`);
    }
    const semantic = requiredString(payload, 'result_semantic');
    if (!RESULT_SEMANTICS.has(semantic as ResultSemantic)) {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', `未知结果语义 ${semantic}`);
    }
    if (!Array.isArray(payload.message_parts)) {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', 'run.completed.message_parts 必须是数组');
    }
    validateResponse(payload.response);
  } else if (eventType === 'run.failed') {
    requiredString(payload, 'code');
    requiredString(payload, 'message');
    requiredBoolean(payload, 'retryable');
  } else if (eventType === 'run.cancelled') {
    if (requiredString(payload, 'code') !== 'RUN_CANCELLED') {
      throw new ChatStreamProtocolError('INVALID_EVENT_PAYLOAD', 'run.cancelled.code 必须为 RUN_CANCELLED');
    }
  }
  return payload as unknown as ChatStreamEvent;
}

function legacySeq(payload: JsonRecord, context: LegacyContext): number {
  const sequence = payload.sequence;
  if (Number.isInteger(sequence) && Number(sequence) > 0) {
    context.nextSeq = Math.max(context.nextSeq, Number(sequence));
    return Number(sequence);
  }
  context.nextSeq += 1;
  return context.nextSeq;
}

function legacyEnvelope(
  eventType: ChatStreamEventType,
  payload: JsonRecord,
  context: LegacyContext,
): JsonRecord {
  const data = record(payload.data);
  const traceId = typeof payload.trace_id === 'string' && payload.trace_id ? payload.trace_id : context.runId;
  const conversationId = typeof data.conversation_id === 'string' && data.conversation_id
    ? data.conversation_id
    : context.conversationId;
  context.runId = traceId;
  context.conversationId = conversationId;
  return {
    seq: legacySeq(payload, context),
    run_id: traceId,
    conversation_id: conversationId,
    message_id: context.messageId,
    timestamp: typeof payload.timestamp === 'string' && payload.timestamp ? payload.timestamp : new Date().toISOString(),
    event_type: eventType,
  };
}

function inferLegacySemantic(response: ChatResponse): ResultSemantic {
  const responseRecord = response as unknown as JsonRecord;
  const assistant = record(responseRecord.assistant_message);
  const direct = responseRecord.result_semantic ?? assistant.result_semantic;
  if (typeof direct === 'string' && RESULT_SEMANTICS.has(direct as ResultSemantic)) return direct as ResultSemantic;
  if (assistant.status === 'FAILED' || assistant.error_code) return 'FAILED';
  const responsePayload = record(assistant.response_payload);
  const analysis = record(responsePayload.analysis);
  const primary = record(analysis.primary);
  const data = isRecord(primary.data) ? primary.data : primary;
  const execution = record(data.execution);
  if (execution.row_count === 0) return 'NO_ROWS';
  return 'VALUE';
}

function legacyMessageParts(response: ChatResponse): MessagePart[] {
  const responseRecord = response as unknown as JsonRecord;
  const assistant = record(responseRecord.assistant_message);
  const parts = responseRecord.message_parts ?? assistant.message_parts;
  if (Array.isArray(parts)) return parts as MessagePart[];
  return typeof assistant.content === 'string' && assistant.content
    ? [{ type: 'text', text: assistant.content }]
    : [];
}

function normalizeLegacy(
  frame: SseFrame,
  payload: JsonRecord,
  context: LegacyContext,
): ChatStreamEvent | null {
  const data = record(payload.data);
  if (frame.event === 'accepted') {
    return { ...legacyEnvelope('run.started', payload, context) } as unknown as ChatStreamEvent;
  }
  if (frame.event === 'answer_delta') {
    const delta = typeof data.text === 'string' ? data.text : typeof payload.text === 'string' ? payload.text : '';
    if (!delta) {
      legacySeq(payload, context);
      return null;
    }
    return { ...legacyEnvelope('answer.delta', payload, context), delta } as unknown as ChatStreamEvent;
  }
  if (frame.event === 'result') {
    const response = validateResponse(payload);
    const assistant = response.assistant_message;
    return {
      ...legacyEnvelope('run.completed', {}, context),
      status: assistant.status === 'PARTIAL' ? 'PARTIAL' : 'SUCCEEDED',
      result_semantic: inferLegacySemantic(response),
      message_parts: legacyMessageParts(response),
      response,
    } as ChatRunCompletedEvent;
  }
  if (frame.event === 'error') {
    const code = typeof data.code === 'string' ? data.code : typeof payload.code === 'string' ? payload.code : 'CHAT_STREAM_FAILED';
    const message = typeof data.message === 'string' ? data.message : typeof payload.message === 'string' ? payload.message : '请求执行失败';
    return {
      ...legacyEnvelope('run.failed', payload, context), code, message, retryable: Boolean(data.retryable ?? payload.retryable),
    } as unknown as ChatStreamEvent;
  }
  if (frame.event === 'cancelled') {
    return {
      ...legacyEnvelope('run.cancelled', payload, context), code: 'RUN_CANCELLED', message: '请求已取消',
    } as unknown as ChatStreamEvent;
  }
  if (frame.event === 'heartbeat') {
    return { ...legacyEnvelope('heartbeat', payload, context) } as unknown as ChatStreamEvent;
  }
  if (frame.event === 'chart_ready' || frame.event === 'completed') {
    legacySeq(payload, context);
    return null;
  }
  const stage = frame.event === 'progress' && typeof payload.stage === 'string'
    ? payload.stage.toLowerCase()
    : frame.event;
  if (stage === 'completed') {
    legacySeq(payload, context);
    return null;
  }
  const phase = LEGACY_PHASES[stage];
  if (phase) {
    return {
      ...legacyEnvelope('phase.started', payload, context),
      phase,
      label: PHASE_LABELS[phase],
      metadata: {},
    } as unknown as ChatStreamEvent;
  }
  throw new ChatStreamProtocolError('UNKNOWN_LEGACY_EVENT', `不支持的旧流式事件 ${frame.event}`);
}

function normalizeFrame(frame: SseFrame, context: LegacyContext): ChatStreamEvent | null {
  const payload = parseJson(frame.data);
  if (typeof payload.event_type === 'string') return validateCanonical(frame, payload);
  return normalizeLegacy(frame, payload, context);
}

function abortError(message = '请求已取消'): Error {
  if (typeof DOMException !== 'undefined') return new DOMException(message, 'AbortError');
  const error = new Error(message);
  error.name = 'AbortError';
  return error;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function publicErrorMessage(body: unknown, fallback: string): string {
  if (!isRecord(body)) return fallback;
  if (typeof body.detail === 'string' && body.detail) return body.detail;
  if (typeof body.message === 'string' && body.message) return body.message;
  return fallback;
}

async function throwHttpError(response: Response): Promise<never> {
  let body: unknown = {};
  try {
    body = JSON.parse(await response.text()) as unknown;
  } catch {
    body = {};
  }
  if (response.status === 401 && typeof window !== 'undefined') {
    window.dispatchEvent(new Event('chatbi:unauthorized'));
  }
  throw new ApiError(response.status, publicErrorMessage(body, `请求失败 (${response.status})`));
}

function isUnauthorizedCode(code: string): boolean {
  const normalized = code.toUpperCase();
  return normalized === 'UNAUTHORIZED'
    || normalized === 'UNAUTHENTICATED'
    || normalized === 'AUTHENTICATION_REQUIRED'
    || normalized.includes('401');
}

export async function streamChat(
  input: ChatInput,
  handlers: ChatStreamHandlers,
  signal: AbortSignal,
): Promise<ChatResponse> {
  let state: ChatRunState = 'IDLE';
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const batcher = new DeltaBatcher(handlers.onDelta);
  const transition = (next: ChatRunState, event?: ChatStreamEvent) => {
    if (state === next) return;
    state = next;
    handlers.onStateChange?.(next, event);
  };

  try {
    if (signal.aborted) throw abortError();
    transition('SUBMITTING');
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
      signal,
    });
    if (!response.ok) return await throwHttpError(response);
    if (!response.body) throw new ChatStreamProtocolError('MISSING_RESPONSE_BODY', '浏览器不支持流式响应');

    reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseDecoder();
    const context: LegacyContext = {
      runId: `LEGACY-${input.client_message_id}`,
      conversationId: input.conversation_id,
      messageId: `pending-${input.client_message_id}`,
      nextSeq: 0,
    };
    let activeRunId = '';
    let activeConversationId = '';
    let activeMessageId = '';
    let lastSeq = 0;
    let answer = '';
    let terminal = false;
    let finalResponse: ChatResponse | undefined;
    let terminalError: Error | undefined;

    const consume = (frame: SseFrame) => {
      if (terminal) return;
      const event = normalizeFrame(frame, context);
      if (!event) return;
      if (!activeRunId) {
        if (event.event_type !== 'run.started') {
          throw new ChatStreamProtocolError('RUN_STARTED_REQUIRED', 'run.started 必须是首个事件');
        }
        activeRunId = event.run_id;
        activeConversationId = event.conversation_id;
        activeMessageId = event.message_id;
      } else if (
        event.run_id !== activeRunId
        || event.conversation_id !== activeConversationId
        || event.message_id !== activeMessageId
      ) {
        throw new ChatStreamProtocolError('EVENT_IDENTITY_CHANGED', '同一次运行的 envelope 身份字段发生变化');
      }
      if (event.seq <= lastSeq) return;
      lastSeq = event.seq;

      if (event.event_type === 'run.started') {
        transition('RUNNING', event);
        handlers.onEvent?.(event);
        return;
      }
      if (event.event_type === 'answer.delta') {
        transition('STREAMING', event);
        handlers.onEvent?.(event);
        answer += event.delta;
        batcher.append(event.delta, event);
        return;
      }
      if (event.event_type === 'run.completed') {
        batcher.flush();
        if (event.response.assistant_message.content !== answer) {
          throw new ChatStreamProtocolError(
            'FINAL_RESPONSE_MISMATCH',
            '最终回答与流式 answer.delta 拼接结果不一致',
          );
        }
        handlers.onEvent?.(event);
        transition('COMPLETED', event);
        finalResponse = event.response;
        terminal = true;
        return;
      }
      if (event.event_type === 'run.failed') {
        batcher.flush();
        handlers.onEvent?.(event);
        transition('FAILED', event);
        if (isUnauthorizedCode(event.code)) {
          if (typeof window !== 'undefined') window.dispatchEvent(new Event('chatbi:unauthorized'));
          terminalError = new ApiError(401, event.message);
        } else {
          terminalError = new ChatStreamError(event.code, event.message, event.retryable);
        }
        terminal = true;
        return;
      }
      if (event.event_type === 'run.cancelled') {
        batcher.flush();
        handlers.onEvent?.(event);
        transition('CANCELLED', event);
        terminalError = abortError(event.message);
        terminal = true;
        return;
      }
      handlers.onEvent?.(event);
    };

    while (!terminal) {
      const { done, value } = await reader.read();
      const frames = done
        ? parser.end(decoder.decode())
        : parser.feed(decoder.decode(value, { stream: true }));
      for (const frame of frames) consume(frame);
      if (done) break;
    }

    if (finalResponse) return finalResponse;
    if (terminalError) throw terminalError;
    throw new ChatStreamProtocolError('MISSING_TERMINAL_EVENT', '流式回答未返回规范终态');
  } catch (error) {
    batcher.flush();
    if (signal.aborted || isAbortError(error)) {
      transition('CANCELLED');
      throw isAbortError(error) ? error : abortError();
    }
    if (!(['FAILED', 'COMPLETED', 'CANCELLED'] as ChatRunState[]).includes(state)) transition('FAILED');
    throw error;
  } finally {
    if (reader) {
      try {
        await reader.cancel();
      } catch {
        // The connection may already be closed by the browser or server.
      }
      try {
        reader.releaseLock();
      } catch {
        // A closed or errored stream can already have released its lock.
      }
    }
  }
}
