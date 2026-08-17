import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatInput, ChatResponse, Conversation, ConversationDetail, QueryResponse } from '../types/api';

const chatMocks = vi.hoisted(() => ({ conversations: vi.fn(), createConversation: vi.fn(), conversation: vi.fn(), attachments: vi.fn(), stream: vi.fn(), deleteConversation: vi.fn(), deleteAttachment: vi.fn(), upload: vi.fn() }));
const queryMocks = vi.hoisted(() => ({ feedback: vi.fn(), save: vi.fn(), get: vi.fn(), ask: vi.fn() }));
vi.mock('../api/chat', () => ({ chatApi: chatMocks }));
vi.mock('../api/queries', () => ({ queryApi: queryMocks }));
vi.mock('../components/EChart', () => ({ EChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));

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

function response(input: ChatInput, query = result()): ChatResponse {
  const user = { id: `user-${input.client_message_id}`, conversation_id: conversation.id, role: 'user' as const, content: input.content, status: 'COMPLETED', attachment_ids: [], response_payload: {}, trace_payload: {}, created_at: '2026-08-18T00:00:01Z' };
  const assistant = { id: `assistant-${input.client_message_id}`, conversation_id: conversation.id, parent_message_id: user.id, role: 'assistant' as const, content: query.summary, route: 'DATA_QUERY' as const, status: query.status, attachment_ids: [], response_payload: { analysis: { primary: query } }, trace_payload: { route: 'DATA_QUERY' }, error_code: query.error_code, created_at: '2026-08-18T00:00:02Z' };
  return { conversation: { ...conversation, title: input.content }, user_message: user, assistant_message: assistant };
}

function renderAsk(initialEntry = '/') {
  const router = createMemoryRouter([{ path: '/', element: <AskPage /> }, { path: '/ask/results', element: <AskPage results /> }], { initialEntries: [initialEntry] });
  render(<RouterProvider router={router} />); return router;
}

describe('问数据真实多轮界面', () => {
  beforeEach(() => {
    localStorage.clear(); Object.values(chatMocks).forEach((mock) => mock.mockReset()); Object.values(queryMocks).forEach((mock) => mock.mockReset());
    chatMocks.conversations.mockResolvedValue([conversation]); chatMocks.conversation.mockResolvedValue(detail); chatMocks.attachments.mockResolvedValue([]); chatMocks.createConversation.mockResolvedValue(conversation);
    chatMocks.stream.mockImplementation(async (input: ChatInput) => response(input)); queryMocks.feedback.mockResolvedValue({ id: 'feedback', recorded: true }); queryMocks.save.mockResolvedValue({ id: 'answer' });
  });

  it('从空状态提交自然语言问题并展示真实 API 结果', async () => {
    const user = userEvent.setup(); renderAsk(); const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '分析上半年各区域充电收入'); await user.click(screen.getByRole('button', { name: '提交问题' }));
    expect((await screen.findAllByText('分析上半年各区域充电收入')).length).toBeGreaterThan(0); expect(screen.getByRole('heading', { name: '分析结论' })).toBeVisible(); expect(screen.getByRole('img', { name: '真实查询结果图表' })).toBeVisible();
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
    await user.click(screen.getByRole('button', { name: '查看 SQL 与执行明细' })); expect(screen.getByRole('dialog', { name: 'SQL 与执行明细' })).toHaveTextContent('SELECT r.region_name');
    await user.click(screen.getByRole('button', { name: '关闭查询明细' })); await user.click(screen.getByRole('button', { name: '结果有帮助' })); await user.click(screen.getByRole('button', { name: '保存为已验证答案' }));
    expect(queryMocks.feedback).toHaveBeenCalledWith('query-1', 'HELPFUL'); expect(queryMocks.save).toHaveBeenCalledWith('query-1');
  });

  it('流式生成期间可停止且取消不显示伪错误', async () => {
    chatMocks.stream.mockImplementationOnce((_input: ChatInput, _progress: unknown, signal: AbortSignal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }));
    const user = userEvent.setup(); renderAsk(); const input = await screen.findByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '统计全部订单收入'); await user.click(screen.getByRole('button', { name: '提交问题' }));
    await user.click(await screen.findByRole('button', { name: '停止生成' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: '停止生成' })).not.toBeInTheDocument());
    expect(screen.queryByRole('heading', { name: '回答未完成' })).not.toBeInTheDocument();
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
