import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { datasourceApi } from '../api/datasources';
import { semanticApi } from '../api/semantic';

export const useDatasources = () => useQuery({ queryKey: ['datasources'], queryFn: datasourceApi.list });
export const useDatasource = (id: string) => useQuery({ queryKey: ['datasource', id], queryFn: () => datasourceApi.get(id), enabled: Boolean(id) });
export const useSchemas = (id: string) => useQuery({ queryKey: ['schemas', id], queryFn: () => datasourceApi.schemas(id), enabled: Boolean(id) });
export const useTables = (id: string, schema?: string) => useQuery({ queryKey: ['tables', id, schema], queryFn: () => datasourceApi.tables(id, schema), enabled: Boolean(id && schema) });
export const useColumns = (id: string, table: string, schema?: string) => useQuery({ queryKey: ['columns', id, schema, table], queryFn: () => datasourceApi.columns(id, table, schema), enabled: Boolean(id && schema && table) });
export const useSemanticModels = () => useQuery({ queryKey: ['semantic-models'], queryFn: semanticApi.list });
export const useSemanticModel = (id: string) => useQuery({ queryKey: ['semantic-model', id], queryFn: () => semanticApi.get(id), enabled: Boolean(id) });

export function useRefresh(keys: string[]) {
  const client = useQueryClient();
  return useMutation({ mutationFn: async () => undefined, onSuccess: () => keys.forEach((key) => client.invalidateQueries({ queryKey: [key] })) });
}
