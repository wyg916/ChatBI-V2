import { api } from './client';
import type { AnswerInput, AnswerLibraryResponse, Dashboard, DashboardCard, DashboardDetail, DashboardInput, DashboardLibraryResponse, QueryResponse, VerifiedAnswer } from '../types/api';

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
  answer: (id: string) => api<VerifiedAnswer>(`/answers/${id}`),
  updateAnswerStatus: (id: string, status: VerifiedAnswer['status'], feedback?: string) => api<VerifiedAnswer>(`/answers/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status, feedback }) }),
  reuseAnswer: (id: string) => api<QueryResponse>(`/answers/${id}/reuse`, { method: 'POST' }),
  dashboards: (options: { query?: string; sort?: string; page?: number; pageSize?: number } = {}) =>
    api<DashboardLibraryResponse>(`/dashboards?${params({ query: options.query, sort: options.sort, page: options.page, page_size: options.pageSize })}`),
  dashboard: (id: string) => api<DashboardDetail>(`/dashboards/${id}`),
  createDashboard: (input: DashboardInput) => api<Dashboard>('/dashboards', { method: 'POST', body: JSON.stringify(input) }),
  addDashboardCard: (dashboardId: string, answerId: string) => api<DashboardCard>(`/dashboards/${dashboardId}/cards`, { method: 'POST', body: JSON.stringify({ answer_id: answerId }) }),
  refreshDashboardCard: (dashboardId: string, cardId: string) => api<DashboardCard>(`/dashboards/${dashboardId}/cards/${cardId}/refresh`, { method: 'POST' }),
  deleteDashboardCard: (dashboardId: string, cardId: string) => api<void>(`/dashboards/${dashboardId}/cards/${cardId}`, { method: 'DELETE' }),
};
