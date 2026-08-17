import { api } from './client';
import type { EvaluationOverview } from '../types/api';

export const evaluationApi = {
  overview: () => api<EvaluationOverview>('/evaluation/overview'),
};
