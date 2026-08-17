import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import { contentApi } from '../api/content';
import { evaluationApi } from '../api/evaluation';
import { DashboardDetailPage } from '../pages/DashboardDetailPage';
import { EvaluationOverviewPage } from '../pages/EvaluationOverviewPage';
import type { DashboardDetail, EvaluationOverview } from '../types/api';

const dashboard: DashboardDetail = {
  dashboard: { id: 'd1', name: '经营总览看板', description: '经营数据', card_count: 8, is_shared: true, refresh_count_today: 2, status: 'REALTIME', trend_variant: 0, updated_at: '2026-08-17T00:00:00Z' },
  data_as_of: '2026-08-17', range_start: '2026-07-19', range_end: '2026-08-17',
  kpis: [
    { label: '总收入', value: 184000000, unit: '元', change: 12.3, change_unit: '%' },
    { label: '总利润', value: 3864000, unit: '元', change: 8.7, change_unit: '%' },
    { label: '利润率', value: 18.7, unit: '%', change: 1.9, change_unit: 'pp' },
    { label: '活跃客户', value: 1268, unit: '个', change: -4.2, change_unit: '%' },
  ],
  revenue_trend: [{ date: '2026-08-17', revenue: 32000000 }],
  regions: [{ region: '华东', order_count: 956, revenue: 36635000, charging_kwh: 82648, margin_percent: 12.8, change_percent: 8.6 }],
  insight: '华东收入领先。', cards: [],
};

const evaluation: EvaluationOverview = {
  current: { id: 'e1', release_name: 'Day 4 Golden 50', model_name: 'Local Runtime Provider', status: 'PASS', is_current: true, golden_set_count: 50, sql_generation_rate: 100, result_accuracy: 100, semantic_accuracy: 100, relevance_accuracy: 100, average_response_seconds: 0.1, error_distribution: [{ label: '无错误', percent: 100, color: '#16a36a' }], trend_points: [{ date: '08/17', value: 100 }], completed_at: '2026-08-17T06:00:00Z', duration_seconds: 3, sql_execution_pass_count: 50, result_value_pass_count: 50, semantic_pass_count: 50, dangerous_sql_total: 38, dangerous_sql_block_count: 38 },
  metrics: [
    { key: 'sql_generation_rate', label: 'SQL 生成率', value: 98.8, unit: '%', change: 1.6 },
    { key: 'result_accuracy', label: '结果集准确率', value: 96.4, unit: '%', change: 1.2 },
    { key: 'semantic_accuracy', label: '语义理解准确率', value: 97.1, unit: '%', change: 0.8 },
    { key: 'average_response_seconds', label: '平均响应时间', value: 3.2, unit: 's', change: -0.4 },
  ],
  comparisons: [],
};
const evaluationRun = evaluation.current;
evaluation.comparisons = [evaluationRun];

function renderRoute(path: string, element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: '/dashboards/:id', element }, { path: '/evaluation', element }], { initialEntries: [path] });
  return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}

test('经营看板详情渲染 API 指标、图表和洞察', async () => {
  vi.spyOn(contentApi, 'dashboard').mockResolvedValue(dashboard);
  renderRoute('/dashboards/d1', <DashboardDetailPage />);
  expect(await screen.findByTestId('dashboard-detail')).toBeInTheDocument();
  expect(screen.getByText('经营总览看板')).toBeInTheDocument();
  expect(screen.getByText('华东收入领先。')).toBeInTheDocument();
});

test('评测中心总览渲染数据库评测记录', async () => {
  vi.spyOn(evaluationApi, 'overview').mockResolvedValue(evaluation);
  renderRoute('/evaluation', <EvaluationOverviewPage />);
  expect(await screen.findByTestId('evaluation-overview')).toBeInTheDocument();
  expect(screen.getAllByText('Day 4 Golden 50').length).toBeGreaterThan(0);
  expect(screen.getByText('最近评测运行')).toBeInTheDocument();
});
