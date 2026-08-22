import { api } from './client';

export interface GovernanceCoverage {
  source: string;
  complete: boolean;
  warnings: string[];
}

export interface CostBreakdown {
  key: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_cny: number;
  cache_hits: number;
  fallbacks: number;
  premium_escalations: number;
  errors: number;
  average_latency_ms: number;
}

export interface CostDashboard {
  coverage: GovernanceCoverage;
  currency: 'CNY';
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_cny: number;
  cache_hits: number;
  fallbacks: number;
  premium_escalations: number;
  errors: number;
  average_latency_ms: number;
  by_workspace: CostBreakdown[];
  by_user: CostBreakdown[];
  by_conversation: CostBreakdown[];
  by_provider: CostBreakdown[];
  by_model: CostBreakdown[];
  by_route: CostBreakdown[];
  entries: Array<{
    id: string;
    workspace_id: string;
    trace_id: string;
    user_id?: string;
    conversation_id?: string;
    provider: string;
    model: string;
    route?: string;
    status: string;
    input_tokens: number;
    output_tokens: number;
    cost_cny: number;
    latency_ms: number;
    created_at: string;
  }>;
}

export interface CostFilters {
  from?: string;
  to?: string;
  user_id?: string;
  conversation_id?: string;
  route?: string;
  provider?: string;
  model?: string;
}

export interface TraceSummary {
  trace_id: string;
  route?: string;
  status: string;
  started_at: string;
  duration_ms: number;
  stage_count: number;
  provider?: string;
  model?: string;
  tools: string[];
  has_sql: boolean;
  has_rag: boolean;
  has_agent: boolean;
  has_file: boolean;
  has_vision: boolean;
  artifact_count: number;
  error_code?: string;
}

export interface TraceDashboard {
  coverage: GovernanceCoverage;
  trace_granularity: 'COMPLETION_RECEIPT_LEVEL' | 'STAGE_LEVEL';
  items: TraceSummary[];
}

export interface TraceDetail {
  coverage: GovernanceCoverage;
  trace: TraceSummary;
  stages: Array<{
    stage: string;
    status: string;
    started_at: string;
    duration_ms: number;
    timing_source: string;
    provider?: string;
    model?: string;
    tool?: string;
    sql?: string;
    error_code?: string;
  }>;
}

export interface ModelProviderGovernance {
  provider: string;
  display_name: string;
  model?: string;
  configured: boolean;
  health: string;
  circuit_state: string;
  requests: number;
  errors: number;
  average_latency_ms: number;
  cost_cny: number;
  fallback_rate: number;
  premium_ratio: number;
}

export interface ModelDashboard {
  coverage: GovernanceCoverage;
  pricing_version: string;
  default_routes: Record<string, string[]>;
  providers: ModelProviderGovernance[];
}

export interface EvaluationGovernanceRun {
  id: string;
  source: 'DATABASE' | 'EVIDENCE';
  suite: string;
  version?: string;
  source_sha?: string;
  status: string;
  pass_rate?: number;
  result_accuracy?: number;
  citation_accuracy?: number;
  runtime_calls?: number;
  errors: string[];
  artifacts: string[];
  evidence_sha256?: string;
  executed_at?: string;
}

export interface EvaluationGovernanceDashboard {
  coverage: GovernanceCoverage;
  runs: EvaluationGovernanceRun[];
}

export const governanceApi = {
  cost: (filters: CostFilters = {}) => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    return api<CostDashboard>(`/governance/cost${query.size ? `?${query.toString()}` : ''}`);
  },
  traces: () => api<TraceDashboard>('/governance/traces'),
  trace: (traceId: string) => api<TraceDetail>(`/governance/traces/${encodeURIComponent(traceId)}`),
  models: () => api<ModelDashboard>('/governance/models'),
  evaluation: () => api<EvaluationGovernanceDashboard>('/governance/evaluation'),
};
