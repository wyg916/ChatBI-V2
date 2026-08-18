import { api } from './client';

export interface CatalogItem {
  kind: 'schema' | 'table' | 'column'; id: string; schema: string; table?: string; name: string;
  qualified_name: string; comment?: string; data_type?: string; primary_key?: boolean; foreign_key?: boolean;
}
export interface CatalogSearch { items: CatalogItem[]; total: number; page: number; page_size: number }
export interface DataRelationship {
  id: string; source_schema: string; source_table: string; source_columns: string[];
  target_schema?: string; target_table: string; target_columns: string[];
}
export interface SqlWorkspaceRun {
  id: string; datasource_id: string; operation: string; sql_text: string; normalized_sql?: string;
  status: string; guard: Record<string, unknown>; execution: {
    columns?: string[]; rows?: Array<Record<string, unknown>>; row_count?: number; duration_ms?: number;
    result_signature?: string; error_code?: string; error_message?: string;
  }; oracle: Record<string, unknown>; duration_ms?: number; error_code?: string; error_message?: string;
  verified_answer_id?: string; created_at: string;
}
export interface SqlHistory { items: SqlWorkspaceRun[]; total: number; page: number; page_size: number }
export interface SampleResult {
  datasource_id: string; schema_name: string; table_name: string; columns: string[];
  rows: Array<Record<string, unknown>>; row_count: number; page: number; page_size: number;
  masked_columns: string[]; result_signature?: string;
}

const params = (values: Record<string, string | number | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== '') search.set(key, String(value)); });
  return search.toString();
};

export const dataWorkspaceApi = {
  search: (datasourceId: string, query = '', kind = 'all', page = 1, pageSize = 50) =>
    api<CatalogSearch>(`/data-workspace/datasources/${datasourceId}/search?${params({ q: query, kind, page, page_size: pageSize })}`),
  relationships: (datasourceId: string) =>
    api<DataRelationship[]>(`/data-workspace/datasources/${datasourceId}/relationships`),
  sample: (datasourceId: string, schema: string, table: string, page = 1, pageSize = 50) =>
    api<SampleResult>(`/data-workspace/datasources/${datasourceId}/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/sample?${params({ page, page_size: pageSize })}`),
  format: (datasourceId: string, sql: string) =>
    api<{ dialect: string; formatted_sql: string }>('/data-workspace/sql/format', { method: 'POST', body: JSON.stringify({ datasource_id: datasourceId, sql }) }),
  execute: (datasourceId: string, sql: string, rowLimit = 200) =>
    api<SqlWorkspaceRun>('/data-workspace/sql/execute', { method: 'POST', body: JSON.stringify({ datasource_id: datasourceId, sql, row_limit: rowLimit }) }),
  explain: (datasourceId: string, sql: string, rowLimit = 200) =>
    api<SqlWorkspaceRun>('/data-workspace/sql/explain', { method: 'POST', body: JSON.stringify({ datasource_id: datasourceId, sql, row_limit: rowLimit }) }),
  history: (datasourceId: string, page = 1, pageSize = 20) =>
    api<SqlHistory>(`/data-workspace/sql/history?${params({ datasource_id: datasourceId, page, page_size: pageSize })}`),
  replay: (runId: string) => api<SqlWorkspaceRun>(`/data-workspace/sql/history/${runId}/replay`, { method: 'POST' }),
  verify: (runId: string) => api<{ run_id: string; answer_id: string; status: string; result_signature: string }>(
    `/data-workspace/sql/history/${runId}/verify`, { method: 'POST', body: JSON.stringify({ owner_name: '当前用户', status: 'VERIFIED' }) },
  ),
};
