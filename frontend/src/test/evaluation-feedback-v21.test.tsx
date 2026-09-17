import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { evaluationApi } from '../api/evaluation';
import { EvaluationOverviewPage } from '../pages/EvaluationOverviewPage';
import type { EvaluationDashboard, EvaluationOverview, EvaluationRun, FeedbackDashboard } from '../types/api';


const run: EvaluationRun = {
  id: 'run-1', release_name: 'ChatBI V2.1 Golden 50', model_name: 'deterministic', status: 'PASS', is_current: true,
  golden_set_count: 50, sql_generation_rate: 100, result_accuracy: 100, semantic_accuracy: 100, relevance_accuracy: 100,
  average_response_seconds: 0.1, error_distribution: [{ label: '无错误', percent: 100, color: '#16a36a' }],
  trend_points: [{ date: '08/18', value: 100 }], completed_at: '2026-08-18T08:00:00Z', duration_seconds: 2,
  manifest_sha256: 'a'.repeat(64), sql_execution_pass_count: 50, result_value_pass_count: 50, semantic_pass_count: 50,
  dangerous_sql_total: 38, dangerous_sql_block_count: 38, multiple_ground_truth: true,
  profile: { model: 'deterministic', prompt: 'chatbi-eval-v2.1', semantic_engine: 'chatbi-semantic', nl2sql_engine: 'chatbi-nl2sql', version: 'v2.1' },
  accuracy: { metric: 1, dimension: 1, time: 1, filter: 1, join: 1, result_value: 1, chart: 1, narrative: 1 },
  release_gate: { status: 'PASS' },
};

const overview: EvaluationOverview = {
  current: run,
  metrics: [
    { key: 'sql_generation_rate', label: 'SQL 执行成功率', value: 100, unit: '%', change: 0 },
    { key: 'result_accuracy', label: '结果值准确率', value: 100, unit: '%', change: 0 },
    { key: 'semantic_accuracy', label: '语义匹配准确率', value: 100, unit: '%', change: 0 },
    { key: 'average_response_seconds', label: '平均响应时间', value: 0.1, unit: 's', change: 0 },
  ],
  comparisons: [run, { ...run, id: 'run-2', release_name: 'Prompt B', profile: { ...run.profile!, prompt: 'prompt-b' } }],
};

const dashboard: EvaluationDashboard = {
  current: run,
  accuracy_cards: Object.entries(run.accuracy!).map(([key, value]) => ({ key, label: key, value, passed: true })),
  error_analysis: [],
  release_gate: { run_id: run.id, status: 'PASS', thresholds: {}, metrics: {}, checks: [] },
  comparison_axes: ['model', 'prompt', 'semantic_engine', 'nl2sql_engine', 'version'],
};

const feedback: FeedbackDashboard = {
  terminology: [{ term: '营收', synonyms: ['收入'], definition: '已确认收入', mapped_object: 'metric.revenue' }],
  sql_examples: [],
  workflows: [{
    answer_id: 'answer-1', query_run_id: 'query-2', status: 'DRAFT', workflow_state: 'CORRECTION_SUBMITTED',
    question: '按地区统计收入', corrected_sql: 'SELECT 1', oracle_status: 'PASSED', version: 1, feedback: {},
  }],
  total_replays: 0,
  passed_replays: 0,
  feedback_replay_rate: 0,
};

function renderPage(path = '/evaluation') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/evaluation" element={<EvaluationOverviewPage />} /></Routes></MemoryRouter></QueryClientProvider>);
}

describe('v2.1 评测与反馈闭环页面', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(evaluationApi, 'overview').mockResolvedValue(overview);
    vi.spyOn(evaluationApi, 'dashboard').mockResolvedValue(dashboard);
  });

  it('展示八类 Oracle 指标并按创建后执行', async () => {
    const user = userEvent.setup();
    vi.spyOn(evaluationApi, 'create').mockResolvedValue({ ...run, id: 'created-1', status: 'CREATED' });
    const execute = vi.spyOn(evaluationApi, 'execute').mockResolvedValue({ run, cases: [] });
    renderPage();
    const accuracyGrid = await screen.findByTestId('oracle-accuracy-grid');
    expect(accuracyGrid).toBeVisible();
    expect(within(accuracyGrid).getAllByText('100%')).toHaveLength(8);
    await user.click(screen.getByRole('button', { name: '新建评测' }));
    await user.click(await screen.findByRole('button', { name: '执行已创建评测' }));
    expect(execute).toHaveBeenCalledWith('created-1');
  });

  it('展示反馈审核、召回和安全回放入口', async () => {
    const user = userEvent.setup();
    vi.spyOn(evaluationApi, 'feedbackDashboard').mockResolvedValue(feedback);
    vi.spyOn(evaluationApi, 'review').mockResolvedValue({ ...feedback.workflows[0], status: 'VERIFIED', workflow_state: 'VERIFIED_SQL', version: 2 });
    vi.spyOn(evaluationApi, 'recall').mockResolvedValue({ candidates: [{ answer_id: 'answer-1', question: '按地区统计收入', sql: 'SELECT 1', score: 0.9, version: 2, status: 'VERIFIED' }] });
    const replay = vi.spyOn(evaluationApi, 'replay').mockResolvedValue({ candidate: { answer_id: 'answer-1', question: '按地区统计收入', sql: 'SELECT 1', score: 0.9, version: 2, status: 'VERIFIED' }, query_run_id: 'replay-1', guard_status: 'PASS', oracle_status: 'PASSED', replay_passed: true, replay_rate: 1 });
    renderPage('/evaluation?view=feedback');
    expect(await screen.findByTestId('feedback-page')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '审核通过' }));
    const recallInput = screen.getByPlaceholderText('再次提出相似问题');
    await user.type(recallInput, '按区域统计营收');
    await user.click(screen.getByRole('button', { name: '召回候选' }));
    await user.click(await screen.findByRole('button', { name: '正式安全回放' }));
    expect(replay).toHaveBeenCalledWith('answer-1', '按区域统计营收');
  });
});
