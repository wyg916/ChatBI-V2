import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { semanticApi } from '../api/semantic';
import { useDatasources, useSemanticModel, useSemanticModels } from '../hooks/useData';
import { SemanticEditorPage } from '../pages/SemanticEditorPage';
import { SemanticModelsPage } from '../pages/SemanticModelsPage';
import type { SemanticModel } from '../types/api';

vi.mock('../hooks/useData', () => ({
  useDatasources: vi.fn(),
  useSemanticModel: vi.fn(),
  useSemanticModels: vi.fn(),
}));

const models: SemanticModel[] = [
  {
    id: 'model-1', name: '财务分析主题', description: '收入、成本与毛利分析', datasource_id: 'source-1', status: 'PUBLISHED', version: 2, updated_at: '2026-08-16T11:42:00Z',
    entities: [
      { id: 'entity-1', name: 'orders', source_table: 'orders', primary_key: 'order_id', time_dimension: 'order_date' },
      { id: 'entity-2', name: 'customers', source_table: 'customers', primary_key: 'customer_id', time_dimension: 'created_at' },
    ],
    metrics: [{ id: 'metric-1', name: 'revenue', label: '收入', expression: 'orders.revenue', aggregation: 'SUM' }],
    dimensions: [{ id: 'dimension-1', name: 'region', label: '地区', source_column: 'orders.region_id', type: 'STRING' }],
    relationships: [{ id: 'relation-1', left_entity: 'orders', right_entity: 'customers', join_type: 'LEFT', join_keys: [{ left: 'customer_id', right: 'customer_id' }], cardinality: 'MANY_TO_ONE' }],
    business_terms: [{ id: 'term-1', term: '收入', synonyms: ['营收'], definition: '订单收入总额', mapped_object: 'metric.revenue' }],
  },
  { id: 'model-2', name: '客户增长主题', description: '新增与留存分析', datasource_id: 'source-2', status: 'DRAFT', version: 1, updated_at: '2026-08-16T10:34:00Z' },
];

function queryResult<T>(data: T) {
  return { data, isLoading: false, error: null } as never;
}

function renderRoute(path: string, element: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([
    { path: '/semantic-models', element: <SemanticModelsPage /> },
    { path: '/semantic-models/:id', element },
  ], { initialEntries: [path] });
  render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
}

describe('语义模型高保真界面', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(useSemanticModels).mockImplementation((options = {}) => queryResult(models.filter((model) => {
      const query = options.query?.trim().toLowerCase() ?? '';
      return (!query || `${model.name} ${model.description ?? ''}`.toLowerCase().includes(query))
        && (!options.status || options.status === 'ALL' || model.status === options.status)
        && (!options.datasourceId || options.datasourceId === 'ALL' || model.datasource_id === options.datasourceId);
    })));
    vi.mocked(useSemanticModel).mockReturnValue(queryResult(models[0]));
    vi.mocked(useDatasources).mockReturnValue(queryResult([
      { id: 'source-1', name: '经营分析库', type: 'postgresql', host: '', port: 5432, database: '', username: '' },
      { id: 'source-2', name: '客户分析库', type: 'mysql', host: '', port: 3306, database: '', username: '' },
    ]));
  });

  it('用 Backend API 数据渲染模型卡片、状态计数和变更记录', async () => {
    const user = userEvent.setup();
    renderRoute('/semantic-models', <SemanticEditorPage />);
    expect(screen.getByRole('heading', { name: '语义模型' })).toBeVisible();
    expect(screen.getByText('1 个启用中')).toBeVisible();
    expect(screen.getByText('1 个草稿')).toBeVisible();
    expect(screen.getAllByTestId('semantic-model-card')).toHaveLength(2);
    expect(screen.getByRole('heading', { name: '模型更新时间' })).toBeVisible();
    expect(screen.getAllByText('Backend API').length).toBeGreaterThan(0);

    await user.type(screen.getByRole('textbox', { name: '搜索语义模型' }), '客户');
    expect(screen.getAllByTestId('semantic-model-card')).toHaveLength(1);
    expect(screen.getByText('客户增长主题')).toBeVisible();
  });

  it('在关系画布选择真实资源并通过现有 API 保存配置', async () => {
    const user = userEvent.setup();
    const searchResources = vi.spyOn(semanticApi, 'searchResources').mockResolvedValue(models[0].entities!);
    vi.spyOn(semanticApi, 'updateResource').mockResolvedValue(models[0].entities![0]);
    vi.spyOn(semanticApi, 'update').mockResolvedValue(models[0]);
    renderRoute('/semantic-models/model-1', <SemanticEditorPage />);

    expect(screen.getByRole('heading', { name: '模型编辑器' })).toBeVisible();
    expect(screen.getByRole('heading', { name: '实体配置' })).toBeVisible();
    expect(screen.getByRole('button', { name: /orders/ })).toBeVisible();
    expect(screen.getByText(/数据库更新：/)).toBeVisible();
    expect(screen.getByRole('button', { name: '查询缓存策略' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '全量缓存策略' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '部门' })).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: '搜索模型资源' }), 'orders');
    await waitFor(() => expect(searchResources).toHaveBeenCalledWith('model-1', 'entities', 'orders'));
    const nameInput = screen.getByLabelText('实体名称');
    await user.clear(nameInput);
    await user.type(nameInput, 'sales_orders');
    await user.click(screen.getByTestId('save-model'));

    await waitFor(() => expect(semanticApi.updateResource).toHaveBeenCalledWith('model-1', 'entities', 'entity-1', expect.objectContaining({ name: 'sales_orders' })));
    expect(await screen.findByText('模型草稿已保存')).toBeVisible();
  });

  it('支持拖动实体、关系线随动并在浏览器中保存无重叠布局', async () => {
    Object.defineProperty(window, 'PointerEvent', { value: MouseEvent, configurable: true });
    renderRoute('/semantic-models/model-1', <SemanticEditorPage />);

    const orders = screen.getByRole('button', { name: 'orders，可拖动' });
    const before = orders.style.transform;
    expect(screen.getByText('1 条关系')).toBeVisible();
    expect(document.querySelectorAll('.semantic-connectors > path')).toHaveLength(1);

    fireEvent.pointerDown(orders, { pointerId: 7, clientX: 120, clientY: 100 });
    fireEvent.pointerMove(orders, { pointerId: 7, clientX: 188, clientY: 128 });
    expect(orders.style.transform).not.toBe(before);
    fireEvent.pointerUp(orders, { pointerId: 7, clientX: 188, clientY: 128 });

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem('chatbi:semantic-layout:model-1:entities') ?? '{}') as Record<string, { x: number; y: number }>;
      expect(saved['entity-1']).toBeDefined();
      expect(saved['entity-2']).toBeDefined();
      expect(saved['entity-1']).not.toEqual(saved['entity-2']);
    });
  });
});
