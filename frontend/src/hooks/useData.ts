import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { datasourceApi } from '../api/datasources';
import { semanticApi } from '../api/semantic';

export const useDatasources = (options: { query?: string; type?: string; status?: string } = {}) => useQuery({
  queryKey: ['datasources', options.query ?? '', options.type ?? 'all', options.status ?? 'all'],
  queryFn: () => datasourceApi.list(options),
});
export const useDatasource = (id: string) => useQuery({ queryKey: ['datasource', id], queryFn: () => datasourceApi.get(id), enabled: Boolean(id) });
export const useSchemas = (id: string) => useQuery({ queryKey: ['schemas', id], queryFn: () => datasourceApi.schemas(id), enabled: Boolean(id) });
export const useTables = (id: string, schema?: string, query?: string) => useQuery({ queryKey: ['tables', id, schema, query ?? ''], queryFn: () => datasourceApi.tables(id, schema, query), enabled: Boolean(id && schema) });
export const useColumns = (id: string, table: string, schema?: string) => useQuery({ queryKey: ['columns', id, schema, table], queryFn: () => datasourceApi.columns(id, table, schema), enabled: Boolean(id && schema && table) });
export const useSemanticModels = (options: { query?: string; status?: string; datasourceId?: string } = {}) => useQuery({
  queryKey: ['semantic-models', options.query ?? '', options.status ?? 'ALL', options.datasourceId ?? 'ALL'],
  queryFn: () => semanticApi.list(options),
});
export const useSemanticModel = (id: string) => useQuery({ queryKey: ['semantic-model', id], queryFn: () => semanticApi.get(id), enabled: Boolean(id) });

export function useRefresh(keys: string[]) {
  const client = useQueryClient();
  return useMutation({ mutationFn: async () => undefined, onSuccess: () => keys.forEach((key) => client.invalidateQueries({ queryKey: [key] })) });
}
