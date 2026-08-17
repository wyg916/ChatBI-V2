export type DatasourceKind = 'postgresql' | 'mysql';

export interface ModelProviderStatus {
  id: string;
  display_name: string;
  model_name: string | null;
  base_url: string | null;
  configured: boolean;
  active: boolean;
  external_model: boolean;
  structured_output: boolean;
  protocol: 'openai-chat-completions' | 'local';
  credential_env: string | null;
}

export interface ModelProviderCatalog {
  active_provider: string;
  secrets_exposed: false;
  items: ModelProviderStatus[];
}

export interface SecurityUser {
  id: string; email: string; display_name: string; role: 'ADMIN' | 'ANALYST'; status: string; last_active_at?: string;
}
export interface SecurityRole { name: 'ADMIN' | 'ANALYST'; permissions: string[]; user_count: number }
export interface SecurityAuditEvent {
  id: string; actor_email: string; action: string; resource_type: string; resource_id?: string;
  status: string; details: Record<string, unknown>; created_at: string;
}
export interface SecurityOverview {
  current_actor?: SecurityUser; user_count: number; role_count: number; active_user_count: number; audit_event_count: number;
  users: SecurityUser[]; roles: SecurityRole[]; audit_events: SecurityAuditEvent[];
}

export interface Datasource {
  id: string;
  name: string;
  type: DatasourceKind;
  host: string;
  port: number;
  database: string;
  username: string;
  schema?: string;
  ssl?: boolean;
  status?: 'CONNECTED' | 'SYNCED' | 'CREATED' | 'ERROR' | 'PENDING';
  table_count?: number;
  column_count?: number;
  last_synced_at?: string;
  last_sync_at?: string;
}

export type DatasourceInput = Omit<Datasource, 'id' | 'status' | 'table_count' | 'column_count' | 'last_synced_at'> & { password: string };
export type DatasourceUpdateInput = Partial<Pick<Datasource, 'name' | 'host' | 'port' | 'database' | 'username' | 'schema' | 'ssl'>> & { password?: string };

export interface SchemaInfo { name: string; table_count?: number }
export interface TableInfo { id?: string; name: string; schema?: string; schema_name?: string; qualified_name?: string; comment?: string; column_count?: number }
export interface ColumnInfo {
  name: string; type?: string; data_type?: string; nullable?: boolean; is_nullable?: boolean; primary_key?: boolean; is_primary_key?: boolean; foreign_key?: boolean; is_foreign_key?: boolean;
  default?: string; comment?: string; sample_values?: unknown[];
}

export type SemanticStatus = 'DRAFT' | 'PUBLISHED' | 'DEPRECATED';
export interface SemanticResource { [key: string]: unknown }
export interface SemanticEntity extends SemanticResource { id?: string; name: string; source_table: string; primary_key: string; time_dimension?: string }
export interface Metric extends SemanticResource { id?: string; name: string; label: string; description?: string; expression: string; aggregation: string; filters?: string[] }
export interface Dimension extends SemanticResource { id?: string; name: string; label: string; source_column: string; type: string }
export interface Relationship extends SemanticResource { id?: string; left_entity: string; right_entity: string; join_type: string; join_keys: Array<{ left: string; right: string }>; cardinality: string }
export interface BusinessTerm extends SemanticResource { id?: string; term: string; synonyms: string[]; definition: string; mapped_object: string }

export interface SemanticModel {
  id: string; name: string; description?: string; datasource_id: string; status: SemanticStatus; version?: number | string;
  entities?: SemanticEntity[]; metrics?: Metric[]; dimensions?: Dimension[]; relationships?: Relationship[];
  business_terms?: BusinessTerm[]; updated_at?: string;
}

export interface SemanticModelInput { name: string; description?: string; datasource_id: string }
export interface SemanticVersion {
  id: string; semantic_model_id: string; version: number; snapshot: Record<string, unknown>; published_at: string; is_current: boolean;
}

export type AnswerStatus = 'DRAFT' | 'VERIFIED' | 'REJECTED' | 'DEPRECATED';
export interface VerifiedAnswer {
  id: string; question: string; module: string; sql_synced: boolean; model_name: string; owner_name: string;
  status: AnswerStatus; accuracy_percent: number; adoption_count: number; is_favorite: boolean; updated_at: string;
  query_run_id?: string; sql_text?: string; result_signature?: string; semantic_model_version?: number;
  semantic_intent: Record<string, unknown>; sql_plan: Record<string, unknown>; result_snapshot: QueryExecution | Record<string, unknown>;
  chart_spec: ChartSpec | Record<string, never>; narrative: Narrative | Record<string, never>;
  semantic_model_id?: string; datasource_id?: string; oracle_status?: string; feedback: Record<string, unknown>; created_at: string;
}
export interface AnswerSummary {
  total: number; average_accuracy: number; monthly_adoptions: number; pending_review: number;
  favorites: number; drafts: number; published: number; verified: number; rejected: number; deprecated: number;
}
export interface AnswerLibraryResponse { summary: AnswerSummary; items: VerifiedAnswer[]; total: number; page: number; page_size: number }
export interface AnswerInput { question: string; model_name: string; owner_name: string; module?: string; status?: AnswerStatus; accuracy_percent?: number }

export interface Dashboard {
  id: string; name: string; description: string; card_count: number; is_shared: boolean; refresh_count_today: number;
  status: string; trend_variant: number; updated_at: string;
}
export interface DashboardSummary { total: number; cards: number; shared: number; refreshes_today: number }
export interface DashboardLibraryResponse { summary: DashboardSummary; items: Dashboard[]; total: number; page: number; page_size: number }
export interface DashboardInput { name: string; description: string; card_count?: number; is_shared?: boolean }

export interface DashboardKpi { label: string; value: number; unit: string; change: number; change_unit: string }
export interface DashboardTrendPoint { date: string; revenue: number }
export interface DashboardRegionRow {
  region: string; order_count: number; revenue: number; charging_kwh: number; margin_percent: number; change_percent: number;
}
export interface DashboardDetail {
  dashboard: Dashboard; data_as_of: string; range_start: string; range_end: string;
  kpis: DashboardKpi[]; revenue_trend: DashboardTrendPoint[]; regions: DashboardRegionRow[]; insight: string; cards: DashboardCard[];
}

export interface DashboardCard {
  id: string; dashboard_id: string; answer_id: string; query_run_id: string; chart_spec: ChartSpec; title: string;
  position: Record<string, number>; size: Record<string, number>; filter_context: Record<string, unknown>;
  semantic_model_version: number; result_signature?: string; refresh_policy: string; source_question: string;
  result_snapshot: QueryExecution; created_at: string; updated_at: string;
}

export interface EvaluationRun {
  id: string; release_name: string; model_name: string; status: string; is_current: boolean; golden_set_count: number;
  sql_generation_rate: number; result_accuracy: number; semantic_accuracy: number; relevance_accuracy: number;
  average_response_seconds: number; error_distribution: Array<{ label: string; percent: number; color: string }>;
  trend_points: Array<{ date: string; value: number }>; completed_at: string; duration_seconds: number;
  manifest_sha256?: string; sql_execution_pass_count: number; result_value_pass_count: number; semantic_pass_count: number;
  dangerous_sql_total: number; dangerous_sql_block_count: number;
}
export interface EvaluationMetric { key: string; label: string; value: number; unit: string; change: number }
export interface EvaluationOverview { current: EvaluationRun; metrics: EvaluationMetric[]; comparisons: EvaluationRun[] }
export interface EvaluationCaseResult {
  id: string; evaluation_run_id: string; case_id: string; category: string; question: string; status: 'PASS' | 'FAIL';
  execution_ok: boolean; result_ok: boolean; semantic_ok: boolean; expected: Record<string, unknown>; actual: Record<string, unknown>;
  generated_sql?: string; result_diff: Array<Record<string, unknown>>; error_category?: string; query_run_id?: string;
  created_at: string; updated_at: string;
}
export interface EvaluationRunDetail { run: EvaluationRun; cases: EvaluationCaseResult[] }
export interface EvaluationCaseDetail { run: EvaluationRun; case: EvaluationCaseResult; previous_case_id?: string; next_case_id?: string }

export interface QueryExecution {
  status?: 'SUCCEEDED' | 'FAILED' | 'TIMEOUT' | 'CONCURRENCY_LIMIT';
  columns?: string[]; column_types?: string[]; rows?: Array<Record<string, unknown>>;
  row_count?: number; truncated?: boolean; duration_ms?: number; normalized_sql?: string;
  result_signature?: string; error_code?: string; error_message?: string;
}
export type ChartType = 'KPI' | 'LINE' | 'BAR' | 'GROUPED_BAR' | 'STACKED_BAR' | 'DONUT' | 'TABLE';
export interface ChartSpec {
  version: string; chart_type: ChartType; title: string; x_field?: string; y_fields: string[];
  series: Array<{ name: string; field: string; type: 'line' | 'bar' | 'pie' | 'kpi' | 'table'; stack?: string }>;
  aggregation: Record<string, string>; unit: Record<string, string>; sort: string[]; limit: number;
  legend: Record<string, unknown>; axis: Record<string, unknown>; tooltip: Record<string, unknown>;
  data_source_query_id: string; result_signature?: string; bound_columns: string[]; bound_row_count: number;
  null_policy: string; warnings: string[];
}
export interface Narrative {
  conclusion: string; key_metrics: Array<{ label: string; value: unknown; unit?: string }>;
  trends: string[]; contributions: string[]; anomalies: string[]; insights: string[]; recommended_questions: string[];
  evidence: Array<{ statement: string; fields: string[]; row_indexes: number[]; evidence_type: string }>;
  source_query_id: string; result_signature?: string; semantic_model_version: number;
}
export interface QueryResponse {
  id: string; question: string; status: 'PLANNING' | 'SUCCEEDED' | 'FAILED' | 'SECURITY_REJECTED' | 'ORACLE_MISMATCH';
  provider: string; datasource_id: string; semantic_model_id: string; semantic_model_version: number;
  context: Record<string, unknown> & { datasource_name?: string; semantic_model_name?: string; linking_trace?: Array<Record<string, unknown>> };
  plan: Record<string, unknown> & {
    generated_sql?: string; normalized_sql?: string; metrics?: string[]; dimensions?: string[];
    filters?: Array<{ field: string; operator: string; value: unknown }>;
    time_range?: { kind: string; start?: string; end_exclusive?: string } | null;
    confidence?: number; warnings?: string[];
  };
  guard: Record<string, unknown> & { allowed?: boolean; normalized_sql?: string; issues?: Array<{ code: string; message: string }> };
  execution: QueryExecution;
  oracle: Record<string, unknown> & {
    status?: 'PASSED' | 'MISMATCH' | 'NOT_RUN'; confidence?: number;
    checks?: Array<{ name: string; passed: boolean; message: string }>; mismatch_count?: number;
  };
  chart_spec: ChartSpec | Record<string, never>;
  narrative: Narrative | Record<string, never>;
  summary: string; kpis: Array<{ label: string; value: unknown; unit?: string }>;
  recommended_questions: string[]; error_code?: string; error_message?: string;
}
