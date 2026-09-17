import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  answerEnvelopeFromResponse,
  mergeFinalResponseMessages,
  mergeUniqueAnswerParts,
  normalizeAnswerEnvelope,
  safeArtifactUrl,
  type AnswerEnvelope,
} from '../chat/answerEnvelope';
import { DynamicAnswerRenderer, formatSqlForDisplay } from '../chat/DynamicAnswerRenderer';
import { sanitizeMarkdownUrl } from '../pages/chat-ui/AnswerMarkdown';
import type { ChatMessage, ChatResponse } from '../types/api';


vi.mock('../charting/EChartsRenderer', () => ({
  EChartsRenderer: ({ label }: { label?: string }) => <div data-testid="controlled-chart">{label}</div>,
}));


function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'assistant-1',
    conversation_id: 'conversation-1',
    parent_message_id: 'user-1',
    role: 'assistant',
    content: '华东收入为 270 元。',
    route: 'DATA_QUERY',
    status: 'SUCCEEDED',
    attachment_ids: [],
    response_payload: {},
    trace_payload: { trace_id: 'trace-1' },
    created_at: '2026-08-22T00:00:00Z',
    ...overrides,
  };
}


function envelope(overrides: Partial<AnswerEnvelope> = {}): AnswerEnvelope {
  const rows = Array.from({ length: 12 }, (_, index) => ({ region: `R${12 - index}`, revenue: 12 - index }));
  return {
    version: '1.0',
    answer_id: 'answer-1',
    conversation_id: 'conversation-1',
    message_id: 'assistant-1',
    trace_id: 'trace-1',
    route: 'DATA_QUERY',
    status: 'SUCCEEDED',
    result_semantic: 'VALUE',
    summary: '华东收入为 270 元。',
    markdown: '华东收入为 **270 元**。\n\n<script>alert(1)</script>\n\n[危险链接](javascript:alert(1)) [公开来源](https://example.com/report)',
    kpis: [{ label: '收入', value: 270, unit: '元' }],
    insights: ['华东贡献最高。'],
    sql: 'SELECT region, SUM(revenue) AS revenue FROM sales WHERE status = \'paid\' GROUP BY region ORDER BY revenue DESC',
    table: { columns: ['region', 'revenue'], rows, row_count: 12, result_signature: 'result-1', truncated: false },
    chart: {
      version: '1', chart_type: 'BAR', title: '区域收入', x_field: 'region', y_fields: ['revenue'],
      series: [{ name: '收入', field: 'revenue', type: 'bar' }], aggregation: {}, unit: { revenue: '元' },
      sort: [], limit: 20, legend: { show: true }, axis: {}, tooltip: {}, data_source_query_id: 'query-1',
      result_signature: 'result-1', bound_columns: ['region', 'revenue'], bound_row_count: 12, null_policy: 'PRESERVE', warnings: [],
    },
    citations: [{ id: 'citation-1', title: '收入口径', version: 'v1', locator: '第 2 节', resource_id: 'document-1' }],
    artifacts: [{ id: 'artifact-1', name: 'sales.csv (CSV)', kind: 'CSV', media_type: 'text/csv', download_url: '/api/v1/attachments/attachment-1/artifact?format=csv' }],
    file_evidence: [{ attachment_id: 'attachment-1', filename: '<img src=x onerror=alert(1)>.csv', kind: 'STRUCTURED', result_signature: 'file-signature' }],
    visual_evidence: [{
      attachment_id: 'image-1', provider: 'kimi', model: 'kimi-k2.6', sanitized_text: '截图显示收入 270。',
      sensitive_classification: 'NONE', injection_detected: false, signature: 'visual-signature',
      claims: [{ claim: '收入', value: 270, locator: 'type:image · tile:0', confidence: 0.99 }],
    }],
    agent_steps: [{ ordinal: 1, code: 'VERIFY', agent_role: 'VerificationAgent', tool_name: 'VERIFY_RESULT', status: 'SUCCEEDED', duration_ms: 12 }],
    warnings: [{ code: 'RESULT_TRUNCATED', message: '结果仅展示前 12 行。', severity: 'INFO' }],
    errors: [],
    cost: { input_tokens: 10, cached_input_tokens: 2, output_tokens: 4, total_tokens: 14, amount_cny: 0.01, exact: true },
    latency: { total_ms: 321, model_ms: 210, time_to_first_token_ms: 42 },
    provider: 'mimo',
    model: 'mimo-v2.5',
    verification: { status: 'VERIFIED', checks: [{ code: 'SQL_GUARD', passed: true, detail: '只读 SQL 安全校验' }], result_signature: 'result-1' },
    follow_up_suggestions: ['按客户查看收入'],
    ...overrides,
  };
}


describe('Phase4 AnswerEnvelope normalizer', () => {
  it('maps the frozen multimodal route to VISION_QUERY and copies only public allowlisted fields', () => {
    const candidate = {
      ...envelope({ route: 'VISION_QUERY' }),
      route: 'MULTIMODAL_QUERY',
      reasoning_content: 'must-not-render',
      private_prompt: 'must-not-render',
      citations: [
        { id: 'citation-1', title: '口径', version: 'v1', locator: '第 1 节', resource_id: 'doc-1', href: 'javascript:alert(1)' },
        { id: 'citation-2', title: '口径重复', version: 'v1', locator: '第 1 节', resource_id: 'doc-1' },
      ],
      artifacts: [
        { id: 'good', name: 'result.csv', kind: 'CSV', download_url: '/api/v1/attachments/a/artifact?format=csv' },
        { id: 'bad', name: 'bad.html', kind: 'HTML', download_url: 'data:text/html,<script>alert(1)</script>' },
      ],
    };
    const normalized = normalizeAnswerEnvelope(message(), candidate);
    expect(normalized.route).toBe('VISION_QUERY');
    expect(normalized.citations).toHaveLength(1);
    expect(normalized.citations[0].href).toBeUndefined();
    expect(normalized.artifacts.map((item) => item.id)).toEqual(['good']);
    expect(JSON.stringify(normalized)).not.toContain('reasoning_content');
    expect(JSON.stringify(normalized)).not.toContain('must-not-render');
    expect(normalized.chart?.axis).toEqual({});
    expect(normalized.chart?.tooltip).toEqual({});
  });

  it('deduplicates streamed parts and final messages by stable identity', () => {
    const citationPart = { type: 'citations', items: [{ title: '口径', version: 'v1', locator: 'L1', resource_id: 'doc-1' }] };
    expect(mergeUniqueAnswerParts([citationPart], [citationPart])).toHaveLength(1);
    const user = message({ id: 'user-1', role: 'user', parent_message_id: undefined, content: '问题' });
    const assistant = message();
    const response = {
      conversation: { id: 'conversation-1', title: '会话', summary: '', active_attachment_ids: [], created_at: '', updated_at: '' },
      user_message: user,
      assistant_message: assistant,
      answer_envelope: envelope(),
    } as ChatResponse & { answer_envelope: AnswerEnvelope };
    const merged = mergeFinalResponseMessages([user, assistant], response);
    expect(merged.map((item) => item.id)).toEqual(['user-1', 'assistant-1']);
    expect(answerEnvelopeFromResponse(response).answer_id).toBe('answer-1');
  });

  it('rejects active-content and cross-scheme URLs', () => {
    expect(sanitizeMarkdownUrl('javascript:alert(1)')).toBe('');
    expect(sanitizeMarkdownUrl('data:text/html,<script>alert(1)</script>')).toBe('');
    expect(sanitizeMarkdownUrl('https://example.com')).toBe('https://example.com');
    expect(safeArtifactUrl('//evil.example/artifact')).toBeUndefined();
    expect(safeArtifactUrl('/api/v1/attachments/a/artifact?format=csv')).toContain('/api/v1/');
  });
});


describe('DynamicAnswerRenderer', () => {
  it('renders every public block dynamically while sanitizing markdown, URLs and filenames', async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    const { container } = render(<DynamicAnswerRenderer envelope={envelope()} onAsk={onAsk} />);

    expect(screen.getByTestId('answer-markdown')).toHaveTextContent('华东收入为 270 元');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('危险链接').closest('a')).toBeNull();
    expect(screen.getByRole('link', { name: '公开来源' })).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByTestId('controlled-chart')).toHaveTextContent('文件分析结果图表');
    expect(screen.getByTestId('answer-kpis')).toHaveTextContent('270元');
    expect(screen.getByTestId('answer-insights')).toHaveTextContent('华东贡献最高');
    expect(screen.getByTestId('answer-citations')).toHaveTextContent('第 2 节');
    expect(screen.getByRole('link', { name: '下载 CSV Artifact' })).toHaveAttribute('href', '/api/v1/attachments/attachment-1/artifact?format=csv');
    expect(screen.getByRole('link', { name: '下载 CSV Artifact' })).toHaveTextContent('sales.csv (CSV)');
    expect(screen.getByTestId('answer-file-evidence')).toHaveTextContent('<img src=x onerror=alert(1)>.csv');
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByTestId('answer-visual-evidence')).toHaveTextContent('置信度 99%');
    expect(screen.getByTestId('answer-agent-steps')).toHaveTextContent('1/1 完成');
    expect(screen.getByTestId('answer-warnings')).toHaveTextContent('RESULT_TRUNCATED');
    expect(screen.getByTestId('answer-runtime-details')).toHaveTextContent('运行与验证信息');

    const table = screen.getByTestId('answer-table');
    await user.click(within(table).getByRole('button', { name: 'revenue' }));
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('R1');
    await user.click(within(table).getByRole('button', { name: '下一页' }));
    expect(within(table).getByText('第 2 / 2 页')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '按客户查看收入' }));
    expect(onAsk).toHaveBeenCalledWith('按客户查看收入');
    await user.click(screen.getByText('查看 SQL'));
    expect(screen.getByTestId('answer-sql')).toHaveTextContent('GROUP BY');
    expect(screen.getByRole('button', { name: '展开' })).toHaveAttribute('aria-expanded', 'false');
    await user.click(screen.getByRole('button', { name: '展开' }));
    expect(screen.getByRole('button', { name: '收起' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('renders retryable errors without any raw payload fallback', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<DynamicAnswerRenderer envelope={envelope({
      status: 'FAILED', result_semantic: 'FAILED', markdown: '', summary: '', kpis: [], insights: [], table: undefined,
      chart: undefined, citations: [], artifacts: [], file_evidence: [], visual_evidence: [], agent_steps: [], warnings: [],
      errors: [{ code: 'MODEL_UNAVAILABLE', message: '当前模型不可用。', retryable: true }], follow_up_suggestions: [],
    })} onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('MODEL_UNAVAILABLE');
    await user.click(screen.getByRole('button', { name: '重新查询' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});


it('formats SQL for display without changing the executable source used for copy', () => {
  expect(formatSqlForDisplay('SELECT a FROM t WHERE id = 1 ORDER BY a')).toBe('SELECT a\nFROM t\nWHERE id = 1\nORDER BY a');
});
