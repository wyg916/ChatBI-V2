import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueryResponse } from '../types/api';

const apiMocks = vi.hoisted(() => ({ ask: vi.fn(), feedback: vi.fn(), save: vi.fn(), get: vi.fn() }));
vi.mock('../api/queries', () => ({ queryApi: apiMocks }));
vi.mock('../components/EChart', () => ({ EChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));

import { AskPage } from '../pages/AskPage';

function result(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    id: 'query-1', question: '按地区统计订单收入', status: 'SUCCEEDED', provider: 'deterministic-semantic-v1',
    datasource_id: 'ds', semantic_model_id: 'sm', semantic_model_version: 2,
    context: { datasource_name: 'Demo PostgreSQL' },
    plan: {
      generated_sql: 'SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM orders o JOIN regions r ON r.region_id=o.region_id GROUP BY r.region_name',
      metrics: ['revenue'], dimensions: ['region'], filters: [], confidence: 0.92,
    },
    guard: { allowed: true, normalized_sql: 'SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM orders o JOIN regions r ON r.region_id = o.region_id GROUP BY r.region_name LIMIT 500' },
    execution: {
      status: 'SUCCEEDED', columns: ['region', 'revenue'], rows: [{ region: '华东', revenue: 128000 }],
      row_count: 1, duration_ms: 12, result_signature: 'abcdef0123456789abcdef0123456789',
    },
    oracle: { status: 'PASSED', confidence: 1, checks: [{ name: 'result', passed: true, message: 'PASS' }], mismatch_count: 0 },
    summary: '查询完成，共返回 1 行结果。', kpis: [], recommended_questions: ['查看最近30天趋势'],
    ...overrides,
  };
}

function renderAsk(initialEntry = '/') {
  const router = createMemoryRouter([
    { path: '/', element: <AskPage /> },
    { path: '/ask/results', element: <AskPage results /> },
  ], { initialEntries: [initialEntry] });
  render(<RouterProvider router={router} />);
  return router;
}

describe('问数据真实查询界面', () => {
  beforeEach(() => {
    apiMocks.ask.mockReset(); apiMocks.feedback.mockReset(); apiMocks.save.mockReset();
    apiMocks.ask.mockImplementation(async (question: string) => result({ question }));
    apiMocks.feedback.mockResolvedValue({ id: 'feedback', recorded: true });
    apiMocks.save.mockResolvedValue({ id: 'answer' });
  });

  it('从空状态提交自然语言问题并展示真实 API 结果', async () => {
    const user = userEvent.setup();
    renderAsk();
    const input = screen.getByRole('textbox', { name: '输入业务问题' });
    await user.type(input, '分析上半年各区域充电收入');
    await user.click(screen.getByRole('button', { name: '提交问题' }));
    expect(await screen.findByText('分析上半年各区域充电收入')).toBeVisible();
    expect(screen.getByRole('heading', { name: '分析结论' })).toBeVisible();
    expect(screen.getByRole('img', { name: '真实查询结果图表' })).toBeVisible();
    expect(screen.getByText('可信度 100%')).toBeVisible();
  });

  it('默认折叠 SQL，点击后展示真实 SQL、签名与结果明细', async () => {
    const user = userEvent.setup();
    renderAsk('/ask/results');
    expect(await screen.findByTestId('query-success')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '查看 SQL 与执行明细' }));
    const dialog = screen.getByRole('dialog', { name: 'SQL 与执行明细' });
    expect(dialog).toHaveTextContent('SELECT r.region_name');
    expect(dialog).toHaveTextContent('SUCCEEDED');
    expect(dialog).toHaveTextContent('真实查询明细');
  });

  it('展示安全拒绝态且不伪装查询结果', async () => {
    apiMocks.ask.mockResolvedValueOnce(result({ status: 'SECURITY_REJECTED', error_code: 'TABLE_NOT_AUTHORIZED', error_message: 'Table denied', execution: {}, oracle: { status: 'NOT_RUN' } }));
    renderAsk('/ask/results');
    expect(await screen.findByTestId('query-security')).toHaveTextContent('TABLE_NOT_AUTHORIZED');
    expect(screen.queryByText('分析结论')).not.toBeInTheDocument();
  });

  it('展示 OracleMismatch 状态', async () => {
    apiMocks.ask.mockResolvedValueOnce(result({ status: 'ORACLE_MISMATCH', oracle: { status: 'MISMATCH', mismatch_count: 2 } }));
    renderAsk('/ask/results');
    expect(await screen.findByTestId('query-mismatch')).toHaveTextContent('2 项差异');
  });

  it('展示真实空结果状态', async () => {
    apiMocks.ask.mockResolvedValueOnce(result({ execution: { status: 'SUCCEEDED', rows: [], row_count: 0 }, summary: '暂无数据' }));
    renderAsk('/ask/results');
    expect(await screen.findByTestId('query-empty')).toHaveTextContent('暂无匹配数据');
  });

  it('反馈与保存写入 Backend API', async () => {
    const user = userEvent.setup();
    renderAsk('/ask/results');
    expect(await screen.findByTestId('query-success')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '结果有帮助' }));
    await user.click(screen.getByRole('button', { name: '保存为标准答案' }));
    expect(apiMocks.feedback).toHaveBeenCalledWith('query-1', 'HELPFUL');
    expect(apiMocks.save).toHaveBeenCalledWith('query-1');
    expect(await screen.findByText('已保存到答案库')).toBeVisible();
  });
});
