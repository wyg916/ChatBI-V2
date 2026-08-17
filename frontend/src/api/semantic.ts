import { api, unwrapList } from './client';
import type { BusinessTerm, Dimension, Metric, Relationship, SemanticEntity, SemanticModel, SemanticModelInput, SemanticVersion } from '../types/api';

type ResourceKind = 'entities' | 'metrics' | 'dimensions' | 'relationships' | 'business-terms';
export const semanticApi = {
  list: () => api<SemanticModel[] | { items: SemanticModel[] }>('/semantic-models').then(unwrapList),
  get: (id: string) => api<SemanticModel>(`/semantic-models/${id}`),
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
