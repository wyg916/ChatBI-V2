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
  insight: '华东收入领先。',
};

const evaluation: EvaluationOverview = {
  current: { id: 'e1', release_name: 'ChatBI Core v1.13', model_name: 'Render v1.2.0 + GPT-4.1', status: 'FULL_RELEASE', is_current: true, golden_set_count: 296, sql_generation_rate: 98.8, result_accuracy: 96.4, semantic_accuracy: 97.1, relevance_accuracy: 96.6, average_response_seconds: 3.2, error_distribution: [{ label: '数据库表', percent: 30, color: '#5b5cf6' }], trend_points: [{ date: '05/19', value: 97.4 }], completed_at: '2026-08-17T06:00:00Z', duration_seconds: 763 },
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
  expect(screen.getByText('ChatBI Core v1.13')).toBeInTheDocument();
  expect(screen.getByText('模型评测表现对比')).toBeInTheDocument();
});
