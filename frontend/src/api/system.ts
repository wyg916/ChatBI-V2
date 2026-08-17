import { api } from './client';
import type { ModelProviderCatalog } from '../types/api';

export const systemApi = {
  modelProviders: () => api<ModelProviderCatalog>('/model-providers'),
};
