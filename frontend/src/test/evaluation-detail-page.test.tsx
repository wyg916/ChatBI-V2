import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { evaluationApi } from '../api/evaluation';
import type { EvaluationCaseDetail, EvaluationRunDetail } from '../types/api';
import { EvaluationDetailPage } from '../pages/EvaluationDetailPage';

const run = {
  id: 'run-1', release_name: 'Day 3 Golden 20', model_name: 'Local Runtime Provider', status: 'PASS', is_current: true,
  golden_set_count: 20, sql_generation_rate: 100, result_accuracy: 100, semantic_accuracy: 100, relevance_accuracy: 100,
  average_response_seconds: 0.1, error_distribution: [{ label: '无错误', percent: 100, color: '#16a36a' }], trend_points: [],
  completed_at: '2026-08-17T08:00:00Z', duration_seconds: 2, manifest_sha256: 'd40bb690a4208240',
  sql_execution_pass_count: 20, result_value_pass_count: 20, semantic_pass_count: 20, dangerous_sql_total: 38, dangerous_sql_block_count: 38,
};
const detail: EvaluationCaseDetail = {
  run,
  case: {
    id: 'case-1', evaluation_run_id: 'run-1', case_id: 'G01', category: 'simple_metric', question: '统计全部订单收入', status: 'PASS',
    execution_ok: true, result_ok: true, semantic_ok: true,
    expected: { sql: 'SELECT SUM(revenue) AS revenue FROM orders', rows: [{ revenue: 100 }], result_signature: 'expected', metrics: ['revenue'], dimensions: [], filters: [] },
    actual: { execution: { rows: [{ revenue: 100 }], result_signature: 'actual' } }, generated_sql: 'SELECT SUM(revenue) AS revenue FROM orders LIMIT 500',
    result_diff: [], query_run_id: 'query-1', created_at: '2026-08-17T08:00:00Z', updated_at: '2026-08-17T08:00:00Z',
  },
  next_case_id: 'G02',
};

function renderDetail(path = '/evaluation/G01') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/evaluation/:id" element={<EvaluationDetailPage />}/></Routes></MemoryRouter></QueryClientProvider>);
}

describe('评测用例详情真实证据界面', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(evaluationApi, 'case').mockResolvedValue(detail);
  });

  it('展示 Expected、Actual、SQL 与持久化 PASS 证据', async () => {
    renderDetail();
    expect(await screen.findByRole('heading', { name: '评测用例详情' })).toBeVisible();
    expect(screen.getByText('统计全部订单收入')).toBeVisible();
    expect(screen.getAllByText('PASS').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('Expected')).toBeVisible();
    expect(screen.getByText('Actual')).toBeVisible();
    expect(screen.getAllByText(/SELECT SUM\(revenue\)/)).toHaveLength(2);
    expect(screen.getByRole('link', { name: '下一条' })).toHaveAttribute('href', '/evaluation/G02');
  });

  it('重新运行调用真实 Golden 20 API', async () => {
    const user = userEvent.setup();
    const runGolden = vi.spyOn(evaluationApi, 'runGolden').mockResolvedValue({ run, cases: [detail.case] } as EvaluationRunDetail);
    renderDetail();
    await screen.findByText('统计全部订单收入');
    await user.click(screen.getByRole('button', { name: '重新运行' }));
    expect(runGolden).toHaveBeenCalledTimes(1);
  });
});
