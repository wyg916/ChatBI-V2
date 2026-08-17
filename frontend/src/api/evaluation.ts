import { api } from './client';
import type { EvaluationCaseDetail, EvaluationOverview, EvaluationRunDetail } from '../types/api';

export const evaluationApi = {
  overview: () => api<EvaluationOverview>('/evaluation/overview'),
  runGolden: () => api<EvaluationRunDetail>('/evaluation/runs', { method: 'POST' }),
  run: (id: string) => api<EvaluationRunDetail>(`/evaluation/runs/${id}`),
  case: (id: string) => api<EvaluationCaseDetail>(`/evaluation/cases/${id}`),
};
