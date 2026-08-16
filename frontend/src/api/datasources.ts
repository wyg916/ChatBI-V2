import { api, unwrapList } from './client';
import type { ColumnInfo, Datasource, DatasourceInput, SchemaInfo, TableInfo } from '../types/api';

export const datasourceApi = {
  list: () => api<Datasource[] | { items: Datasource[] }>('/datasources').then(unwrapList),
  get: (id: string) => api<Datasource>(`/datasources/${id}`),
  create: (input: DatasourceInput) => api<Datasource>('/datasources', { method: 'POST', body: JSON.stringify(input) }),
  test: (id: string) => api<{ success: boolean; message?: string }>(`/datasources/${id}/test`, { method: 'POST' }),
  sync: (id: string) => api<{ success?: boolean; tables?: number; columns?: number }>(`/datasources/${id}/sync`, { method: 'POST' }),
  schemas: (id: string) => api<SchemaInfo[] | { items: SchemaInfo[] }>(`/datasources/${id}/schemas`).then(unwrapList),
  tables: (id: string, schema?: string) => api<TableInfo[] | { items: TableInfo[] }>(`/datasources/${id}/tables${schema ? `?schema=${encodeURIComponent(schema)}` : ''}`).then(unwrapList),
  columns: (id: string, table: string, schema?: string) => api<ColumnInfo[] | { items: ColumnInfo[] }>(`/datasources/${id}/tables/${encodeURIComponent(table)}/columns${schema ? `?schema=${encodeURIComponent(schema)}` : ''}`).then(unwrapList),
};
