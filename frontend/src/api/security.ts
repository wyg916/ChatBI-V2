import { api } from './client';
import type { SecurityOverview } from '../types/api';

export const securityApi = {
  overview: (options: { query?: string; status?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.query) params.set('user_query', options.query);
    if (options.status && options.status !== 'ALL') params.set('user_status', options.status);
    const suffix = params.toString();
    return api<SecurityOverview>(`/security/overview${suffix ? `?${suffix}` : ''}`);
  },
};
