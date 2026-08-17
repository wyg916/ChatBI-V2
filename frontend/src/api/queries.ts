import { api } from './client';
import type { QueryResponse, VerifiedAnswer } from '../types/api';

export const queryApi = {
  ask: (question: string) => api<QueryResponse>('/ask', {
    method: 'POST',
    body: JSON.stringify({ question, row_limit: 500 }),
  }),
  get: (id: string) => api<QueryResponse>(`/queries/${id}`),
  feedback: (id: string, feedbackType: 'HELPFUL' | 'NOT_HELPFUL' | 'INCORRECT', comment?: string) =>
    api<{ id: string; recorded: boolean }>(`/queries/${id}/feedback`, {
      method: 'POST', body: JSON.stringify({ feedback_type: feedbackType, comment }),
    }),
  save: (id: string) => api<VerifiedAnswer>(`/queries/${id}/save`, {
    method: 'POST', body: JSON.stringify({ owner_name: '当前用户', status: 'DRAFT' }),
  }),
};
