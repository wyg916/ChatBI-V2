import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { datasourceApi } from '../api/datasources';
import { DatasourceDetailPage } from '../pages/DatasourceDetailPage';
import { DatasourcesPage } from '../pages/DatasourcesPage';
import type { ColumnInfo, Datasource, SchemaInfo, TableInfo } from '../types/api';

const sources: Datasource[] = [
  {
    id: 'source-pg', name: '财务分析 PostgreSQL', type: 'postgresql', host: 'localhost', port: 5432,
    database: 'chatbi_v2', username: 'readonly', schema: 'public', status: 'SYNCED', table_count: 42,
    column_count: 186, last_sync_at: new Date(Date.now() - 2 * 60_000).toISOString(),
  },
  {
    id: 'source-my', name: 'CRM MySQL', type: 'mysql', host: 'localhost', port: 3306,
    database: 'chatbi_demo_business', username: 'readonly', status: 'ERROR', table_count: 18,
    column_count: 94, last_sync_at: new Date(Date.now() - 11 * 60_000).toISOString(),
  },
];

const schemas: SchemaInfo[] = [{ name: 'public', table_count: 2 }, { name: 'finance', table_count: 1 }];
const publicTables: TableInfo[] = [
  { id: 'table-orders', name: 'orders', schema_name: 'public', qualified_name: 'source-pg.public.orders', comment: '经营订单明细', column_count: 3 },
  { id: 'table-regions', name: 'regions', schema_name: 'public', qualified_name: 'source-pg.public.regions', comment: '区域维度', column_count: 2 },
];
const orderColumns: ColumnInfo[] = [
  { name: 'order_id', data_type: 'varchar(64)', primary_key: true, nullable: false, comment: '订单编号', sample_values: ['ORD-001', 'ORD-002'] },
  { name: 'order_amount', data_type: 'numeric(18,2)', nullable: false, comment: '订单金额', sample_values: [88.6, 62.3] },
  { name: 'finish_time', data_type: 'timestamp', nullable: true, comment: '完成时间', sample_values: ['2026-08-16 10:32', '2026-08-16 10:36'] },
];

function renderRoute(initialEntry: string, detail = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/datasources" element={<DatasourcesPage />} />
          <Route path="/datasources/:id" element={detail ? <DatasourceDetailPage /> : <h1>数据源详情</h1>} />
          <Route path="/semantic-models" element={<h1>语义模型</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe('数据源高保真页面', () => {
  it('通过 Backend API 预览并导入 Excel 数据源', async () => {
    vi.spyOn(datasourceApi, 'list').mockResolvedValue([]);
    const preview = {
      filename: '经营数据.xlsx', file_sha256: 'a'.repeat(64), file_size_bytes: 1024, format: 'xlsx' as const,
      sheet_count: 1, row_count: 2, column_count: 2,
      limits: { max_bytes: 10_485_760, max_rows: 100_000, max_columns_per_sheet: 256, max_sheets: 32 },
      sheets: [{
        source_name: '销售明细', table_name: 'sheet_销售明细', row_count: 2,
        columns: [
          { source_name: 'order_id', name: 'order_id', data_type: 'BIGINT', nullable: false },
          { source_name: 'revenue', name: 'revenue', data_type: 'DOUBLE PRECISION', nullable: false },
        ],
        preview_rows: [{ order_id: 1, revenue: 88.5 }, { order_id: 2, revenue: 120 }],
      }],
    };
    vi.spyOn(datasourceApi, 'previewSpreadsheet').mockResolvedValue(preview);
    const importSpreadsheet = vi.spyOn(datasourceApi, 'importSpreadsheet').mockResolvedValue({
      datasource: {
        id: 'source-excel', name: '经营数据', type: 'excel', host: 'Backend managed', port: 0,
        database: 'Imported spreadsheet', username: 'Managed read-only', status: 'SYNCED', table_count: 1,
        column_count: 2, import_filename: '经营数据.xlsx', import_row_count: 2, import_sheet_count: 1,
      },
      preview,
    });
    const user = userEvent.setup();
    renderRoute('/datasources');

    await user.click(await screen.findByTestId('import-spreadsheet'));
    const file = new File(['safe workbook'], '经营数据.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    await user.upload(screen.getByLabelText('选择 Excel 或 CSV 文件'), file);

    expect(await screen.findByLabelText('表格导入预览')).toHaveTextContent('校验通过');
    expect(screen.getByLabelText('表格导入预览')).toHaveTextContent('销售明细');
    expect(screen.getByDisplayValue('经营数据')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '确认导入并同步元数据' }));

    await waitFor(() => expect(importSpreadsheet).toHaveBeenCalledWith('经营数据', file));
    expect(await screen.findByRole('status')).toHaveTextContent('已导入：1 张工作表、2 行，可用于语义模型和问数');
  });

  it('用 Backend API 统计渲染列表，并支持搜索和状态筛选', async () => {
    const list = vi.spyOn(datasourceApi, 'list').mockImplementation(async (options = {}) => sources.filter((item) => {
      const query = options.query?.trim().toLowerCase() ?? '';
      const matchesQuery = !query || `${item.name} ${item.database}`.toLowerCase().includes(query);
      const matchesType = !options.type || options.type === 'all' || item.type === options.type;
      const normal = item.status === 'CONNECTED' || item.status === 'SYNCED';
      const matchesStatus = !options.status || options.status === 'all' || (options.status === 'normal' ? normal : !normal);
      return matchesQuery && matchesType && matchesStatus;
    }));
    vi.spyOn(datasourceApi, 'sync').mockResolvedValue({ success: true, tables: 2, columns: 5 });
    const user = userEvent.setup();
    renderRoute('/datasources');

    const overview = await screen.findByLabelText('数据源概览');
    expect(overview).toHaveTextContent('数据源总数2');
    expect(overview).toHaveTextContent('正常连接1');
    expect(overview).toHaveTextContent('可用数据表60');
    expect(screen.getAllByTestId('datasource-card')).toHaveLength(2);

    await user.selectOptions(screen.getByLabelText('连接状态'), 'normal');
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ status: 'normal' })));
    expect(await screen.findAllByTestId('datasource-card')).toHaveLength(1);
    expect(screen.getByText('财务分析 PostgreSQL')).toBeVisible();

    await user.selectOptions(screen.getByLabelText('连接状态'), 'all');
    await user.type(screen.getByLabelText('搜索数据源'), 'CRM');
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ query: 'CRM' })));
    expect(await screen.findAllByTestId('datasource-card')).toHaveLength(1);
    expect(screen.getByText('CRM MySQL')).toBeVisible();

    await user.clear(screen.getByLabelText('搜索数据源'));
    await user.click(screen.getByRole('button', { name: '↻ 同步全部数据源' }));
    await waitFor(() => expect(datasourceApi.sync).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('status')).toHaveTextContent('已完成 2 个数据源的元数据同步');
  });

  it('展示真实 Schema、字段角色和样例值，并可切换 Schema', async () => {
    vi.spyOn(datasourceApi, 'get').mockResolvedValue(sources[0]);
    vi.spyOn(datasourceApi, 'schemas').mockResolvedValue(schemas);
    const tables = vi.spyOn(datasourceApi, 'tables').mockImplementation(async (_id, schema, query) => {
      const rows = schema === 'finance'
        ? [{ id: 'table-budget', name: 'budget', schema_name: 'finance', qualified_name: 'source-pg.finance.budget', column_count: 2 }]
        : publicTables;
      return query ? rows.filter((item) => item.name.includes(query)) : rows;
    });
    vi.spyOn(datasourceApi, 'columns').mockImplementation(async (_id, table) => table === 'orders' ? orderColumns : []);
    const user = userEvent.setup();
    renderRoute('/datasources/source-pg', true);

    expect(await screen.findByRole('heading', { name: 'Schema 与字段管理' })).toBeVisible();
    expect(await screen.findByRole('button', { name: /orders/ })).toBeVisible();
    const columnTable = screen.getByTestId('column-table');
    expect(await within(columnTable).findByText('order_amount')).toBeVisible();
    expect(within(columnTable).getByText('度量')).toBeVisible();
    expect(screen.getByText('ORD-001')).toBeVisible();
    expect(screen.getByDisplayValue('经营订单明细')).toBeVisible();

    await user.type(screen.getByLabelText('搜索数据表'), 'reg');
    await waitFor(() => expect(tables).toHaveBeenCalledWith('source-pg', 'public', 'reg'));
    expect(await screen.findByRole('button', { name: /regions/ })).toBeVisible();
    expect(screen.queryByRole('button', { name: /orders/ })).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText('搜索数据表'));
    await user.selectOptions(screen.getByLabelText('切换 Schema'), 'finance');
    expect(await screen.findByRole('button', { name: /budget/ })).toBeVisible();
    await waitFor(() => expect(datasourceApi.tables).toHaveBeenCalledWith('source-pg', 'finance', undefined));
  });
});
