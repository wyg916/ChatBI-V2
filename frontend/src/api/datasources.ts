import { api, unwrapList } from './client';
import type { ColumnInfo, Datasource, DatasourceInput, DatasourceUpdateInput, SchemaInfo, TableInfo } from '../types/api';

export const datasourceApi = {
  list: (options: { query?: string; type?: string; status?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.query) params.set('query', options.query);
    if (options.type && options.type !== 'all') params.set('type', options.type);
    if (options.status && options.status !== 'all') params.set('status', options.status);
    const suffix = params.toString();
    return api<Datasource[] | { items: Datasource[] }>(`/datasources${suffix ? `?${suffix}` : ''}`).then(unwrapList);
  },
  get: (id: string) => api<Datasource>(`/datasources/${id}`),
  create: (input: DatasourceInput) => api<Datasource>('/datasources', { method: 'POST', body: JSON.stringify(input) }),
  update: (id: string, input: DatasourceUpdateInput) => api<Datasource>(`/datasources/${id}`, { method: 'PUT', body: JSON.stringify(input) }),
  test: (id: string) => api<{ success: boolean; message?: string }>(`/datasources/${id}/test`, { method: 'POST' }),
  sync: (id: string) => api<{ success?: boolean; tables?: number; columns?: number }>(`/datasources/${id}/sync`, { method: 'POST' }),
  schemas: (id: string) => api<SchemaInfo[] | { items: SchemaInfo[] }>(`/datasources/${id}/schemas`).then(unwrapList),
  tables: (id: string, schema?: string, query?: string) => {
    const params = new URLSearchParams();
    if (schema) params.set('schema', schema);
    if (query) params.set('query', query);
    const suffix = params.toString();
    return api<TableInfo[] | { items: TableInfo[] }>(`/datasources/${id}/tables${suffix ? `?${suffix}` : ''}`).then(unwrapList);
  },
  columns: (id: string, table: string, schema?: string) => api<ColumnInfo[] | { items: ColumnInfo[] }>(`/datasources/${id}/tables/${encodeURIComponent(table)}/columns${schema ? `?schema=${encodeURIComponent(schema)}` : ''}`).then(unwrapList),
};
