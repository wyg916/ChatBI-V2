import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { contentApi } from '../api/content';
import { AnswerLibraryPage } from '../pages/AnswerLibraryPage';
import { DashboardListPage } from '../pages/DashboardListPage';
import type { AnswerLibraryResponse, DashboardLibraryResponse } from '../types/api';

const answers: AnswerLibraryResponse = {
  summary: { total: 128, average_accuracy: 96.4, monthly_adoptions: 1284, pending_review: 14, favorites: 128, drafts: 14, published: 1, verified: 1, rejected: 0, deprecated: 113 },
  items: [
    { id: 'a1', question: '2026年二季度环比增长率入围多少?', module: '模块 C1.1.8', sql_synced: true, model_name: '全体收入', owner_name: '文心', status: 'VERIFIED', accuracy_percent: 98, adoption_count: 432, is_favorite: true, semantic_intent: {}, sql_plan: {}, result_snapshot: {}, chart_spec: {}, narrative: {}, feedback: {}, created_at: '2026-08-17T08:00:00Z', updated_at: '2026-08-17T08:00:00Z' },
    { id: 'a2', question: '过去 30 天退款笔数最高的商品', module: '模块 C1.1.8', sql_synced: true, model_name: '订单与发票', owner_name: '弘岳', status: 'DRAFT', accuracy_percent: 89, adoption_count: 182, is_favorite: true, semantic_intent: {}, sql_plan: {}, result_snapshot: {}, chart_spec: {}, narrative: {}, feedback: {}, created_at: '2026-08-17T08:00:00Z', updated_at: '2026-08-17T08:00:00Z' },
  ], total: 128, page: 1, page_size: 6,
};

const dashboards: DashboardLibraryResponse = {
  summary: { total: 18, cards: 147, shared: 9, refreshes_today: 36 },
  items: [
    { id: 'd1', name: '经营总览看板', description: '收入、利润、订单与客户增长总览', card_count: 8, is_shared: true, refresh_count_today: 5, status: 'REALTIME', trend_variant: 0, updated_at: new Date().toISOString() },
    { id: 'd2', name: '区域经营看板', description: '各区域收入、订单、毛利与完成率', card_count: 12, is_shared: true, refresh_count_today: 4, status: 'REALTIME', trend_variant: 1, updated_at: new Date().toISOString() },
  ], total: 18, page: 1, page_size: 6,
};

function renderPage(path: string, element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path, element }, { path: '/dashboards/:id', element: <div>看板详情</div> }, { path: '/ask/results', element: <div>问数结果</div> }], { initialEntries: [path] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}

describe('答案库和看板列表高保真界面', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('从 Backend API 渲染答案统计、分类和表格', async () => {
    vi.spyOn(contentApi, 'answers').mockResolvedValue(answers);
    renderPage('/answers', <AnswerLibraryPage />);

    expect(await screen.findByText('1,284')).toBeVisible();
    expect(screen.getByText('96.4%')).toBeVisible();
    expect(screen.getAllByTestId('answer-row')).toHaveLength(2);
    expect(screen.getByRole('tab', { name: '已验证 1' })).toBeVisible();
    expect(screen.getByText('过去 30 天退款笔数最高的商品')).toBeVisible();
  });

  it('新建标准答案通过 API 保存并刷新列表', async () => {
    const user = userEvent.setup();
    vi.spyOn(contentApi, 'answers').mockResolvedValue(answers);
    const create = vi.spyOn(contentApi, 'createAnswer').mockResolvedValue(answers.items[0]);
    renderPage('/answers', <AnswerLibraryPage />);
    await screen.findByText('1,284');

    await user.click(screen.getByRole('button', { name: '＋ 新建标准答案' }));
    await user.type(screen.getByLabelText('标准问题'), '近 12 个月订单量是多少？');
    await user.type(screen.getByLabelText('语义模型'), '订单量');
    await user.click(screen.getByRole('button', { name: '保存标准答案' }));

    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ question: '近 12 个月订单量是多少？', model_name: '订单量' })));
  });

  it('从 Backend API 渲染看板统计、数据库卡片计数并切换列表视图', async () => {
    const user = userEvent.setup();
    vi.spyOn(contentApi, 'dashboards').mockResolvedValue(dashboards);
    renderPage('/dashboards', <DashboardListPage />);

    expect(await screen.findByText('147')).toBeVisible();
    expect(screen.getAllByTestId('dashboard-card')).toHaveLength(2);
    expect(screen.getAllByText('数据库卡片')).toHaveLength(2);
    expect(document.querySelectorAll('.dashboard-trend img')).toHaveLength(0);
    expect(screen.getByText('经营总览看板', { selector: 'h2' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: '列表视图' }));
    expect(screen.getByRole('button', { name: '列表视图' })).toHaveClass('active');
  });
});
