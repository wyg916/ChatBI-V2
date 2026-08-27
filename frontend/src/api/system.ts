import { api } from './client';
import type { AppearanceSettings, ModelProviderCatalog, ModelProviderStatus, SystemInformation, WorkspaceSettings } from '../types/api';

export const systemApi = {
  modelProviders: () => api<ModelProviderCatalog>('/model-providers'),
  testProvider: (id: string) => api<ModelProviderStatus>(`/model-providers/${encodeURIComponent(id)}/test`, { method: 'POST' }),
  setProvider: (id: string, enabled: boolean) => api<ModelProviderStatus>(`/model-providers/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
  settings: () => api<WorkspaceSettings>('/settings'),
  appearance: () => api<AppearanceSettings>('/appearance'),
  saveSettings: (body: Record<string, unknown>) => api<WorkspaceSettings>('/settings', { method: 'PATCH', body: JSON.stringify(body) }),
  information: () => api<SystemInformation>('/system-information'),
};
