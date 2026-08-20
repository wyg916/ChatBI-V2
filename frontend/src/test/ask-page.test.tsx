import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Attachment, ChatInput, ChatResponse, Conversation, ConversationDetail, QueryResponse } from '../types/api';

const chatMocks = vi.hoisted(() => ({ conversations: vi.fn(), createConversation: vi.fn(), conversation: vi.fn(), attachments: vi.fn(), stream: vi.fn(), cancelStream: vi.fn(), deleteConversation: vi.fn(), deleteAttachment: vi.fn(), upload: vi.fn() }));
const queryMocks = vi.hoisted(() => ({ feedback: vi.fn(), save: vi.fn(), get: vi.fn(), ask: vi.fn() }));
vi.mock('../api/chat', () => ({ chatApi: chatMocks }));
vi.mock('../api/queries', () => ({ queryApi: queryMocks }));
vi.mock('../components/EChart', () => ({ EChart: ({ label, className = '' }: { label: string; className?: string }) => <div className={`data-echart ${className}`} role="img" aria-label={label} /> }));

import { AskPage } from '../pages/AskPage';

function result(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    id: 'query-1', question: '按地区统计订单收入', status: 'SUCCEEDED', provider: 'deterministic-semantic-v1', datasource_id: 'ds', semantic_model_id: 'sm', semantic_model_version: 2,
    context: { datasource_name: 'Demo PostgreSQL' },
    plan: { generated_sql: 'SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM orders o JOIN regions r ON r.region_id=o.region_id GROUP BY r.region_name', metrics: ['revenue'], dimensions: ['region'], filters: [], confidence: 0.92 },
    guard: { allowed: true, normalized_sql: 'SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM orders o JOIN regions r ON r.region_id = o.region_id GROUP BY r.region_name LIMIT 500' },
    execution: { status: 'SUCCEEDED', columns: ['region', 'revenue'], rows: [{ region: '华东', revenue: 128000 }], row_count: 1, duration_ms: 12, result_signature: 'abcdef0123456789abcdef0123456789' },
    oracle: { status: 'PASSED', confidence: 1, checks: [{ name: 'result', passed: true, message: 'PASS' }], mismatch_count: 0 },
    chart_spec: { version: '1.0', chart_type: 'BAR', title: '按region revenue', x_field: 'region', y_fields: ['revenue'], series: [{ name: 'revenue', field: 'revenue', type: 'bar' }], aggregation: { revenue: 'SUM' }, unit: { revenue: '元' }, sort: [], limit: 20, legend: { show: false }, axis: {}, tooltip: {}, data_source_query_id: 'query-1', result_signature: 'abcdef0123456789abcdef0123456789', bound_columns: ['region', 'revenue'], bound_row_count: 1, null_policy: 'PRESERVE', warnings: [] },
    narrative: { conclusion: '华东收入为 128,000 元。', key_metrics: [], trends: [], contributions: ['华东收入最高'], anomalies: [], insights: ['华东收入最高'], recommended_questions: ['查看最近30天趋势'], evidence: [{ statement: '华东收入最高', fields: ['region', 'revenue'], row_indexes: [0], evidence_type: 'CONTRIBUTION' }], source_query_id: 'query-1', result_signature: 'abcdef0123456789abcdef0123456789', semantic_model_version: 2 },
    summary: '查询完成，共返回 1 行结果。', kpis: [], recommended_questions: ['查看最近30天趋势'], ...overrides,
  } as QueryResponse;
}

const conversation: Conversation = { id: 'conversation-1', title: '新会话', summary: '', active_attachment_ids: [], created_at: '2026-08-18T00:00:00Z', updated_at: '2026-08-18T00:00:00Z' };
const detail: ConversationDetail = { ...conversation, messages: [] };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function readyAttachment(id: string, conversationId: string, filename: string): Attachment {
  return {
    id, conversation_id: conversationId, filename, extension: 'csv', mime_type: 'text/csv', kind: 'STRUCTURED',
    size_bytes: 128, status: 'READY', created_at: '2026-08-19T00:00:00Z', expires_at: '2026-08-20T00:00:00Z',
  };
}

function response(input: ChatInput, query = result(), target = conversation): ChatResponse {
  const user = { id: `user-${input.client_message_id}`, conversation_id: target.id, role: 'user' as const, content: input.content, status: 'COMPLETED', attachment_ids: [], response_payload: {}, trace_payload: {}, created_at: '2026-08-18T00:00:01Z' };
  const assistant = { id: `assistant-${input.client_message_id}`, conversation_id: target.id, parent_message_id: user.id, role: 'assistant' as const, content: query.summary, route: 'DATA_QUERY' as const, status: query.status, attachment_ids: [], response_payload: { analysis: { primary: query } }, trace_payload: { route: 'DATA_QUERY' }, error_code: query.error_code, created_at: '2026-08-18T00:00:02Z' };
  return { conversation: { ...target, title: input.content }, user_message: user, assistant_message: assistant };
}

function renderAsk(initialEntry = '/') {
  const router = createMemoryRouter([{ path: '/', element: <AskPage /> }, { path: '/ask/results', element: <AskPage results /> }], { initialEntries: [initialEntry] });
  render(<RouterProvider router={router} />); return router;
}

describe('问数据真实多轮界面', () => {
  beforeEach(() => {
    localStorage.clear(); Object.values(chatMocks).forEach((mock) => mock.mockReset()); Object.values(queryMocks).forEach((mock) => mock.mockReset());
    chatMocks.conversations.mockResolvedValue([conversation]); chatMocks.conversation.mockResolvedValue(detail); chatMocks.attachments.mockResolvedValue([]); chatMocks.createConversation.mockResolvedValue(conversation);
    chatMocks.cancelStream.mockResolvedValue({ cancelled: true });
    chatMocks.stream.mockImplementation(async (input: ChatInput) => response(input)); queryMocks.feedback.mockResolvedValue({ id: 'feedback', recorded: true }); queryMocks.save.mockResolvedValue({ id: 'answer' });
  });

  it('从空状态提交自然语言问题并展示真实 API 结果', async () => {
    const user = userEvent.setup(); renderAsk(); const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '分析上半年各区域充电收入'); await user.click(screen.getByRole('button', { name: '提交问题' }));
    expect((await screen.findAllByText('分析上半年各区域充电收入')).length).toBeGreaterThan(0); expect(screen.getByRole('heading', { name: '分析结论' })).toBeVisible();
    const chart = screen.getByRole('img', { name: '真实查询结果图表' });
    expect(chart).toBeVisible();
    expect(chart).toHaveClass('data-echart', 'analysis-chart');
    expect(chart.closest('.chart-card')).not.toBeNull();
  });

  it('空态创建会话未完成时快速双击只启动一次流', async () => {
    const delayedCreate = deferred<Conversation>();
    chatMocks.conversations.mockResolvedValueOnce([]);
    chatMocks.createConversation.mockReturnValueOnce(delayedCreate.promise);

    const user = userEvent.setup();
    renderAsk();
    const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '分析本月收入');
    const submit = screen.getByRole('button', { name: '提交问题' });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(chatMocks.createConversation).toHaveBeenCalledTimes(1);
    expect(chatMocks.stream).not.toHaveBeenCalled();
    delayedCreate.resolve(conversation);

    await waitFor(() => expect(chatMocks.stream).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('分析本月收入', { selector: '.chat-user-bubble p' })).toBeVisible();
  });

  it('等待创建会话时新建本地会话会使旧提交失效', async () => {
    const delayedCreate = deferred<Conversation>();
    chatMocks.conversations.mockResolvedValueOnce([]);
    chatMocks.createConversation.mockReturnValueOnce(delayedCreate.promise);

    const user = userEvent.setup();
    renderAsk();
    const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '不应继续的旧问题');
    fireEvent.click(screen.getByRole('button', { name: '提交问题' }));
    expect(chatMocks.createConversation).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: '＋ 新会话' }));

    await act(async () => {
      delayedCreate.resolve(conversation);
      await delayedCreate.promise;
    });

    expect(chatMocks.stream).not.toHaveBeenCalled();
    expect(localStorage.getItem('chatbi_conversation_id')).toBeNull();
    expect(screen.queryByText('不应继续的旧问题', { selector: '.chat-user-bubble p' })).not.toBeInTheDocument();
  });

  it('快速打开 B 后再打开 C 时，迟到的 B 响应不会覆盖 C', async () => {
    const conversationB: Conversation = { ...conversation, id: 'conversation-b', title: 'B 会话' };
    const conversationC: Conversation = { ...conversation, id: 'conversation-c', title: 'C 会话' };
    const detailB = deferred<ConversationDetail>();
    const detailC = deferred<ConversationDetail>();
    const attachmentsB = deferred<Attachment[]>();
    const attachmentsC = deferred<Attachment[]>();
    const fileB = readyAttachment('attachment-b', conversationB.id, 'B附件.csv');
    const fileC = readyAttachment('attachment-c', conversationC.id, 'C附件.csv');
    chatMocks.conversations.mockResolvedValueOnce([conversation, conversationB, conversationC]);
    chatMocks.conversation.mockImplementation((id: string) => {
      if (id === conversationB.id) return detailB.promise;
      if (id === conversationC.id) return detailC.promise;
      return Promise.resolve(detail);
    });
    chatMocks.attachments.mockImplementation((id: string) => {
      if (id === conversationB.id) return attachmentsB.promise;
      if (id === conversationC.id) return attachmentsC.promise;
      return Promise.resolve([]);
    });

    const user = userEvent.setup();
    renderAsk();
    await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.click(screen.getByRole('button', { name: /B 会话/ }));
    await user.click(screen.getByRole('button', { name: /C 会话/ }));

    await act(async () => {
      detailC.resolve({ ...conversationC, messages: [] });
      attachmentsC.resolve([fileC]);
      await Promise.all([detailC.promise, attachmentsC.promise]);
    });
    expect(screen.getByRole('button', { name: /C 会话/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('C附件.csv')).toBeVisible();
    expect(localStorage.getItem('chatbi_conversation_id')).toBe(conversationC.id);

    await act(async () => {
      detailB.resolve({ ...conversationB, messages: [] });
      attachmentsB.resolve([fileB]);
      await Promise.all([detailB.promise, attachmentsB.promise]);
    });
    expect(screen.getByRole('button', { name: /C 会话/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('C附件.csv')).toBeVisible();
    expect(screen.queryByText('B附件.csv')).not.toBeInTheDocument();
    expect(localStorage.getItem('chatbi_conversation_id')).toBe(conversationC.id);
  });

  it('空态首次上传采用同一会话，随后提问携带就绪附件', async () => {
    const uploaded = readyAttachment('attachment-first', conversation.id, '首传数据.csv');
    chatMocks.conversations.mockResolvedValueOnce([]);
    chatMocks.upload.mockResolvedValueOnce(uploaded);

    const user = userEvent.setup();
    renderAsk();
    const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, { target: { files: [new File(['region,revenue'], '首传数据.csv', { type: 'text/csv' })] } });

    expect(await screen.findByText('就绪')).toBeVisible();
    expect(screen.getByText('首传数据.csv')).toBeVisible();
    expect(chatMocks.createConversation).toHaveBeenCalledTimes(1);
    expect(chatMocks.upload).toHaveBeenCalledWith(conversation.id, expect.any(File), expect.any(Function));
    expect(localStorage.getItem('chatbi_conversation_id')).toBe(conversation.id);

    await user.type(input, '分析上传数据');
    await user.click(screen.getByRole('button', { name: '提交问题' }));
    await waitFor(() => expect(chatMocks.stream).toHaveBeenCalledTimes(1));
    expect(chatMocks.createConversation).toHaveBeenCalledTimes(1);
    expect(chatMocks.stream.mock.calls[0][0]).toMatchObject({ conversation_id: conversation.id, attachment_ids: [uploaded.id] });
  });

  it('上传等待创建会话时新建本地会话不会继续上传或串入附件', async () => {
    const delayedCreate = deferred<Conversation>();
    chatMocks.conversations.mockResolvedValueOnce([]);
    chatMocks.createConversation.mockReturnValueOnce(delayedCreate.promise);

    const user = userEvent.setup();
    renderAsk();
    await screen.findByRole('textbox', { name: '输入业务问题' });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(fileInput!, { target: { files: [new File(['x'], '旧附件.csv', { type: 'text/csv' })] } });
    expect(chatMocks.createConversation).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: '＋ 新会话' }));

    await act(async () => {
      delayedCreate.resolve(conversation);
      await delayedCreate.promise;
    });
    expect(chatMocks.upload).not.toHaveBeenCalled();
    expect(screen.queryByText('旧附件.csv')).not.toBeInTheDocument();
    expect(localStorage.getItem('chatbi_conversation_id')).toBeNull();
  });

  it('Enter 发送、Shift+Enter 换行且中文输入法组合态不误发', async () => {
    const user = userEvent.setup(); renderAsk(); const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '第一行'); await user.keyboard('{Shift>}{Enter}{/Shift}第二行'); expect(input).toHaveValue('第一行\n第二行'); expect(chatMocks.stream).not.toHaveBeenCalled();
    fireEvent.compositionStart(input); fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true }); expect(chatMocks.stream).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input); fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' }); await waitFor(() => expect(chatMocks.stream).toHaveBeenCalledTimes(1));
  });

  it.each([
    ['security', result({ status: 'SECURITY_REJECTED', error_code: 'TABLE_NOT_AUTHORIZED', error_message: 'Table denied', execution: {}, oracle: { status: 'NOT_RUN' } }), 'query-security'],
    ['mismatch', result({ status: 'ORACLE_MISMATCH', oracle: { status: 'MISMATCH', mismatch_count: 2 } }), 'query-mismatch'],
    ['empty', result({ execution: { status: 'SUCCEEDED', rows: [], row_count: 0 }, summary: '暂无数据' }), 'query-empty'],
  ])('展示 %s 真实状态', async (_name, query, testId) => {
    chatMocks.stream.mockImplementationOnce(async (input: ChatInput) => response(input, query as QueryResponse)); renderAsk(`/ask/results?q=${encodeURIComponent('测试问题')}`);
    expect(await screen.findByTestId(testId)).toBeVisible();
  });

  it('默认折叠 SQL 并支持反馈保存', async () => {
    const user = userEvent.setup(); renderAsk(`/ask/results?q=${encodeURIComponent('按地区统计订单收入')}`); expect(await screen.findByTestId('query-success')).toBeVisible();
    const trigger = screen.getByRole('button', { name: '查看 SQL 与执行明细' });
    const composer = screen.getByRole('textbox', { name: '输入业务问题' });
    await user.click(trigger); expect(screen.getByRole('dialog', { name: 'SQL 与执行明细' })).toHaveTextContent('SELECT r.region_name');
    const close = screen.getByRole('button', { name: '关闭查询明细' });
    expect(close).toHaveFocus();
    expect(composer.closest('[inert]')).not.toBeNull();
    await user.keyboard('{Tab}'); expect(close).toHaveFocus();
    await user.keyboard('{Shift>}{Tab}{/Shift}'); expect(close).toHaveFocus();
    await user.click(close);
    expect(trigger).toHaveFocus();
    expect(composer.closest('[inert]')).toBeNull();
    await user.click(screen.getByRole('button', { name: '结果有帮助' })); await user.click(screen.getByRole('button', { name: '保存为已验证答案' }));
    expect(queryMocks.feedback).toHaveBeenCalledWith('query-1', 'HELPFUL'); expect(queryMocks.save).toHaveBeenCalledWith('query-1');
  });

  it('展示受控知识引用、公开分析阶段与文件 Artifact，不暴露内部实现', async () => {
    const user = userEvent.setup();
    chatMocks.conversation.mockResolvedValueOnce({
      ...conversation,
      messages: [{
        id: 'assistant-governed', conversation_id: conversation.id, role: 'assistant', content: '已完成受控分析。',
        route: 'COMPLEX_ANALYSIS', status: 'SUCCEEDED', attachment_ids: [],
        response_payload: {
          analysis: { primary: { steps: [{ code: 'VERIFY', agent_role: 'VerificationAgent', tool_name: 'VERIFY_RESULT', status: 'SUCCEEDED' }], knowledge: { citations: [{ citation_id: 'citation-1', title: '收入口径', text: '退款在确认后冲减收入。', document_version_id: 'version-1', locator: '第 2 节', chunk_id: 'chunk-1' }] } } },
          file_analysis: { operation: 'SUM', trace: { complete: true }, result: { columns: ['region', 'revenue'], rows: [{ region: '华东', revenue: 270 }] }, chart: { chart_type: 'bar', x: 'region', y: 'revenue', rows: [{ region: '华东', revenue: 270 }] }, artifacts: [{ attachment_id: 'attachment-1', csv_url: '/api/v1/attachments/attachment-1/artifact?format=csv', json_url: '/api/v1/attachments/attachment-1/artifact?format=json' }] },
        },
        trace_payload: { trace_id: 'TRACE-GOVERNED-1' }, created_at: '2026-08-18T00:00:02Z',
      }],
    } as ConversationDetail);
    renderAsk();
    expect(await screen.findByTestId('citation-evidence')).toHaveTextContent('版本 version-1');
    await user.click(screen.getByRole('button', { name: '查看 SQL 与执行明细' }));
    expect(screen.getByRole('dialog', { name: 'SQL 与执行明细' })).toHaveTextContent('已校验结果');
    expect(screen.queryByText('VerificationAgent')).not.toBeInTheDocument();
    expect(screen.queryByText('VERIFY_RESULT')).not.toBeInTheDocument();
    expect(screen.queryByText('SUM')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '关闭查询明细' }));
    expect(screen.getByTestId('file-analysis-evidence')).toHaveTextContent('270');
    expect(screen.getByRole('img', { name: '文件分析结果图表' })).toBeVisible();
    expect(screen.getByRole('link', { name: '下载 CSV Artifact' })).toHaveAttribute('href', '/api/v1/attachments/attachment-1/artifact?format=csv');
  });

  it('流式生成期间可停止且取消不显示伪错误', async () => {
    const cancellation = deferred<{ cancelled: boolean }>();
    let streamSignal: AbortSignal | undefined;
    chatMocks.cancelStream.mockReturnValueOnce(cancellation.promise);
    chatMocks.stream.mockImplementationOnce((_input: ChatInput, _progress: unknown, signal: AbortSignal) => new Promise((_resolve, reject) => {
      streamSignal = signal;
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }));
    const user = userEvent.setup(); renderAsk(); const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '统计全部订单收入'); await user.click(screen.getByRole('button', { name: '提交问题' }));
    await user.click(await screen.findByRole('button', { name: '停止生成' }));
    await waitFor(() => expect(chatMocks.cancelStream).toHaveBeenCalledWith(conversation.id, expect.any(String)));
    expect(streamSignal?.aborted).toBe(false);
    cancellation.resolve({ cancelled: true });
    await waitFor(() => expect(screen.queryByRole('button', { name: '停止生成' })).not.toBeInTheDocument());
    expect(streamSignal?.aborted).toBe(true);
    expect(screen.queryByRole('heading', { name: '回答未完成' })).not.toBeInTheDocument();
  });

  it('切换会话会立即取消旧流并释放发送锁，迟到 delta 不串入新会话', async () => {
    const conversationB: Conversation = { ...conversation, id: 'conversation-2', title: 'B 会话', created_at: '2026-08-19T01:00:00Z', updated_at: '2026-08-19T01:00:00Z' };
    const detailB: ConversationDetail = { ...conversationB, messages: [] };
    chatMocks.conversations.mockResolvedValueOnce([conversation, conversationB]);
    chatMocks.conversation.mockImplementation(async (id: string) => id === conversationB.id ? detailB : detail);
    let firstSignal: AbortSignal | undefined;
    let firstHandlers: { onDelta?: (delta: string, event: { event_type: string }) => void } | undefined;
    chatMocks.stream
      .mockImplementationOnce((_input: ChatInput, handlers: typeof firstHandlers, signal: AbortSignal) => {
        firstHandlers = handlers;
        firstSignal = signal;
        return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
      })
      .mockImplementationOnce(async (input: ChatInput) => response(input, result(), conversationB));

    const user = userEvent.setup();
    renderAsk();
    const composer = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(composer, 'A 会话长任务');
    await user.click(screen.getByRole('button', { name: '提交问题' }));
    expect(await screen.findByRole('button', { name: '停止生成' })).toBeVisible();

    const conversationBButton = screen.getByRole('button', { name: /B 会话/ });
    await user.click(conversationBButton);
    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    await waitFor(() => expect(conversationBButton).toHaveAttribute('aria-current', 'page'));
    expect(screen.queryByRole('button', { name: '停止生成' })).not.toBeInTheDocument();
    firstHandlers?.onDelta?.('迟到的 A 内容', { event_type: 'answer.delta' });
    expect(screen.queryByText('迟到的 A 内容')).not.toBeInTheDocument();

    await user.type(composer, 'B 会话新问题');
    const submit = screen.getByRole('button', { name: '提交问题' });
    expect(submit).toBeEnabled();
    await user.click(submit);
    await waitFor(() => expect(chatMocks.stream).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('B 会话新问题', { selector: '.chat-user-bubble p' })).toBeVisible();
    expect(screen.queryByText('A 会话长任务')).not.toBeInTheDocument();
    expect(screen.queryByText('迟到的 A 内容')).not.toBeInTheDocument();
  });

  it('结构化与兼容载荷同时包含同一引用时只渲染一次', async () => {
    chatMocks.conversation.mockResolvedValueOnce({
      ...conversation,
      messages: [{
        id: 'assistant-citations', conversation_id: conversation.id, role: 'assistant', content: '引用已核验。',
        route: 'KNOWLEDGE_QUERY', status: 'SUCCEEDED', attachment_ids: [],
        message_parts: [{ type: 'citations', items: [{ title: '收入口径', version: 'version-1', locator: '第 2 节', resource_id: 'document-1' }] }],
        response_payload: { analysis: { primary: { knowledge: { citations: [{ title: '收入口径', document_version_id: 'version-1', locator: '第 2 节', document_id: 'document-1' }] } } } },
        trace_payload: {}, created_at: '2026-08-18T00:00:02Z',
      }],
    } as ConversationDetail);
    renderAsk();
    const citations = await screen.findByTestId('citation-evidence');
    expect(within(citations).getAllByText('收入口径')).toHaveLength(1);
  });

  it('失败消息支持按原问题重试', async () => {
    chatMocks.stream.mockRejectedValueOnce(new Error('temporary network error')).mockImplementationOnce(async (input: ChatInput) => response(input));
    const user = userEvent.setup(); renderAsk(); const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '按地区统计订单收入'); await user.click(screen.getByRole('button', { name: '提交问题' }));
    expect(await screen.findByRole('heading', { name: '回答未完成' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: '重新查询' }));
    expect(await screen.findByRole('heading', { name: '分析结论' })).toBeVisible();
    expect(chatMocks.stream).toHaveBeenCalledTimes(2);
  });
});
