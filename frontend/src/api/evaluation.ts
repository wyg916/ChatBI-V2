import { api } from './client';
import type {
  EvaluationCaseDetail,
  EvaluationComparison,
  EvaluationCreate,
  EvaluationDashboard,
  EvaluationOverview,
  EvaluationRun,
  EvaluationRunDetail,
  FeedbackCandidate,
  FeedbackDashboard,
  FeedbackReplay,
  FeedbackWorkflow,
} from '../types/api';

export const evaluationApi = {
  overview: () => api<EvaluationOverview>('/evaluation/overview'),
  dashboard: (runId?: string) => api<EvaluationDashboard>(`/evaluation/dashboard${runId ? `?run_id=${encodeURIComponent(runId)}` : ''}`),
  create: (input: EvaluationCreate) => api<EvaluationRun>('/evaluation/definitions', { method: 'POST', body: JSON.stringify(input) }),
  execute: (id: string) => api<EvaluationRunDetail>(`/evaluation/runs/${id}/execute`, { method: 'POST' }),
  compare: (runIds: string[]) => api<EvaluationComparison>('/evaluation/compare', { method: 'POST', body: JSON.stringify({ run_ids: runIds }) }),
  runGolden: () => api<EvaluationRunDetail>('/evaluation/runs', { method: 'POST' }),
  run: (id: string) => api<EvaluationRunDetail>(`/evaluation/runs/${id}`),
  case: (id: string) => api<EvaluationCaseDetail>(`/evaluation/cases/${id}`),
  feedbackDashboard: () => api<FeedbackDashboard>('/evaluation/feedback/dashboard'),
  feedback: (input: { query_run_id: string; sentiment: 'THUMB_UP' | 'THUMB_DOWN'; reason?: 'INCORRECT_RESULT' | 'INCORRECT_SQL' | 'INCORRECT_CHART' | 'CITATION_PROBLEM' | 'OTHER'; comment?: string }) =>
    api<FeedbackWorkflow>('/evaluation/feedback', { method: 'POST', body: JSON.stringify(input) }),
  startReview: (answerId: string, comment?: string) => api<FeedbackWorkflow>(`/evaluation/feedback/${answerId}/review/start`, { method: 'POST', body: JSON.stringify({ comment }) }),
  decide: (answerId: string, input: { decision: 'ACCEPT' | 'REJECT'; comment: string; corrected_sql?: string; expected_columns?: string[]; expected_rows?: Array<Record<string, unknown>>; question_pattern?: string }) =>
    api<FeedbackWorkflow>(`/evaluation/feedback/${answerId}/decision`, { method: 'POST', body: JSON.stringify(input) }),
  correct: (queryRunId: string, comment: string) => api<{ recorded: boolean }>('/evaluation/feedback/correct', { method: 'POST', body: JSON.stringify({ query_run_id: queryRunId, comment }) }),
  incorrect: (input: { query_run_id: string; comment: string; corrected_sql: string; expected_columns: string[]; expected_rows: Array<Record<string, unknown>>; owner_name: string }) =>
    api<FeedbackWorkflow>('/evaluation/feedback/incorrect', { method: 'POST', body: JSON.stringify(input) }),
  review: (answerId: string, decision: 'APPROVE' | 'REJECT', comment: string) => api<FeedbackWorkflow>(`/evaluation/feedback/${answerId}/review`, { method: 'POST', body: JSON.stringify({ decision, comment }) }),
  recall: (question: string) => api<{ candidates: FeedbackCandidate[] }>('/evaluation/feedback/recall', { method: 'POST', body: JSON.stringify({ question }) }),
  replay: (answerId: string, question: string) => api<FeedbackReplay>(`/evaluation/feedback/${answerId}/replay`, { method: 'POST', body: JSON.stringify({ question }) }),
};
