import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { dataWorkspaceApi } from '../api/dataWorkspace';
import { datasourceApi } from '../api/datasources';
import { DataWorkspacePage } from '../pages/DataWorkspacePage';

const source = {
  id: 'source-pg', name: '10M PostgreSQL', type: 'postgresql' as const, host: 'localhost', port: 5432,
  database: 'chatbi_v2', username: 'readonly', schema: 'finance', status: 'SYNCED' as const, table_count: 2, column_count: 5,
};
const run = {
  id: 'run-1', datasource_id: 'source-pg', operation: 'EXECUTE', sql_text: 'SELECT order_id, revenue FROM finance.orders',
  normalized_sql: 'SELECT order_id, revenue FROM finance.orders LIMIT 200', status: 'SUCCEEDED',
  guard: { allowed: true }, execution: { columns: ['order_id', 'revenue'], rows: [{ order_id: 1, revenue: 99.5 }], row_count: 1, duration_ms: 4, result_signature: 'a'.repeat(64) },
  oracle: { status: 'PASSED' }, duration_ms: 4, created_at: '2026-08-18T10:00:00Z',
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/datasources/source-pg/workspace']}><Routes>
    <Route path="/datasources/:id/workspace" element={<DataWorkspacePage />} />
    <Route path="/datasources/:id" element={<div>Schema</div>} />
  </Routes></MemoryRouter></QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

describe('Data Workspace', () => {
  it('connects catalog, lazy masked samples, guarded SQL, history replay and Verified SQL', async () => {
    vi.spyOn(datasourceApi, 'get').mockResolvedValue(source);
    vi.spyOn(datasourceApi, 'schemas').mockResolvedValue([{ name: 'finance', table_count: 2 }]);
    vi.spyOn(datasourceApi, 'tables').mockResolvedValue([{ id: 'orders', name: 'orders', schema_name: 'finance', qualified_name: 'finance.orders', column_count: 3 }]);
    vi.spyOn(datasourceApi, 'columns').mockResolvedValue([
      { name: 'order_id', data_type: 'bigint', nullable: false, primary_key: true, sample_values: [] },
      { name: 'revenue', data_type: 'numeric', nullable: false, sample_values: [] },
    ]);
    vi.spyOn(dataWorkspaceApi, 'search').mockResolvedValue({ items: [{ kind: 'table', id: 'orders', schema: 'finance', name: 'orders', qualified_name: 'finance.orders' }], total: 1, page: 1, page_size: 50 });
    vi.spyOn(dataWorkspaceApi, 'relationships').mockResolvedValue([{ id: 'r1', source_schema: 'finance', source_table: 'orders', source_columns: ['customer_id'], target_schema: 'finance', target_table: 'customers', target_columns: ['customer_id'] }]);
    vi.spyOn(dataWorkspaceApi, 'history').mockResolvedValue({ items: [run], total: 1, page: 1, page_size: 20 });
    vi.spyOn(dataWorkspaceApi, 'sample').mockResolvedValue({ datasource_id: 'source-pg', schema_name: 'finance', table_name: 'orders', columns: ['email'], rows: [{ email: '***MASKED***' }], row_count: 1, page: 1, page_size: 50, masked_columns: ['email'], result_signature: 's'.repeat(64) });
    vi.spyOn(dataWorkspaceApi, 'execute').mockResolvedValue(run);
    vi.spyOn(dataWorkspaceApi, 'verify').mockResolvedValue({ run_id: 'run-1', answer_id: 'answer-123456', status: 'VERIFIED', result_signature: 'a'.repeat(64) });
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole('heading', { name: '数据工作台' })).toBeVisible();
    expect(await screen.findByText('finance.orders')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '懒加载样例值' }));
    expect(await screen.findByText(/MASKED/)).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'SQL 工作区' }));
    await waitFor(() => expect((screen.getByLabelText('SQL 编辑器') as HTMLTextAreaElement).value).toContain('order_id'));
    await user.click(screen.getByTestId('execute-sql'));
    expect(await screen.findByText('99.5')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '保存为 Verified SQL' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Verified SQL 已保存到答案库');
    expect(dataWorkspaceApi.verify).toHaveBeenCalledWith('run-1');
  });
});
