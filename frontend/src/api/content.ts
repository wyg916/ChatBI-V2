import { api } from './client';
import type { AnswerInput, AnswerLibraryResponse, Dashboard, DashboardDetail, DashboardInput, DashboardLibraryResponse, VerifiedAnswer } from '../types/api';

function params(values: Record<string, string | number | undefined>) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  return query.toString();
}

export const contentApi = {
  answers: (options: { query?: string; tab?: string; page?: number; pageSize?: number } = {}) =>
    api<AnswerLibraryResponse>(`/answers?${params({ query: options.query, tab: options.tab, page: options.page, page_size: options.pageSize })}`),
  createAnswer: (input: AnswerInput) => api<VerifiedAnswer>('/answers', { method: 'POST', body: JSON.stringify(input) }),
  dashboards: (options: { query?: string; sort?: string; page?: number; pageSize?: number } = {}) =>
    api<DashboardLibraryResponse>(`/dashboards?${params({ query: options.query, sort: options.sort, page: options.page, page_size: options.pageSize })}`),
  dashboard: (id: string) => api<DashboardDetail>(`/dashboards/${id}`),
  createDashboard: (input: DashboardInput) => api<Dashboard>('/dashboards', { method: 'POST', body: JSON.stringify(input) }),
};
