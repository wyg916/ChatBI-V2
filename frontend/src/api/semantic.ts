import { api, unwrapList } from './client';
import type { BusinessTerm, Dimension, Metric, Relationship, SemanticEntity, SemanticModel, SemanticModelInput, SemanticVersion } from '../types/api';

type ResourceKind = 'entities' | 'metrics' | 'dimensions' | 'relationships' | 'business-terms';
export const semanticApi = {
  list: (options: { query?: string; status?: string; datasourceId?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.query) params.set('query', options.query);
    if (options.status && options.status !== 'ALL') params.set('status', options.status);
    if (options.datasourceId && options.datasourceId !== 'ALL') params.set('datasource_id', options.datasourceId);
    const suffix = params.toString();
    return api<SemanticModel[] | { items: SemanticModel[] }>(`/semantic-models${suffix ? `?${suffix}` : ''}`).then(unwrapList);
  },
  get: (id: string) => api<SemanticModel>(`/semantic-models/${id}`),
  searchResources: (id: string, kind: ResourceKind, query: string) => {
    const params = new URLSearchParams({ kind, query });
    return api<Array<SemanticEntity | Metric | Dimension | Relationship | BusinessTerm>>(`/semantic-models/${id}/resources?${params}`);
  },
  create: (input: SemanticModelInput) => api<SemanticModel>('/semantic-models', { method: 'POST', body: JSON.stringify(input) }),
  update: (id: string, input: Partial<SemanticModel>) => api<SemanticModel>(`/semantic-models/${id}`, { method: 'PUT', body: JSON.stringify(input) }),
  add: <T extends SemanticEntity | Metric | Dimension | Relationship | BusinessTerm>(id: string, kind: ResourceKind, input: T) =>
    api<T>(`/semantic-models/${id}/${kind}`, { method: 'POST', body: JSON.stringify(input) }),
  updateResource: <T extends SemanticEntity | Metric | Dimension | Relationship | BusinessTerm>(id: string, kind: ResourceKind, resourceId: string, input: T) =>
    api<T>(`/semantic-models/${id}/${kind}/${resourceId}`, { method: 'PUT', body: JSON.stringify(input) }),
  publish: (id: string) => api<{ success: boolean; message: string; status: string; version: number }>(`/semantic-models/${id}/publish`, { method: 'POST' }),
  versions: (id: string) => api<SemanticVersion[]>(`/semantic-models/${id}/versions`),
  rollback: (id: string, version: number) => api<{ success: boolean; message: string; status: string; version: number }>(`/semantic-models/${id}/versions/${version}/rollback`, { method: 'POST' }),
};
