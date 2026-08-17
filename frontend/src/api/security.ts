import { api } from './client';
import type { SecurityOverview } from '../types/api';

export const securityApi = {
  overview: () => api<SecurityOverview>('/security/overview'),
};
