export type DatasourceKind = 'postgresql' | 'mysql';

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

export type AnswerStatus = 'DRAFT' | 'REVIEW' | 'PUBLISHED' | 'ARCHIVED';
export interface VerifiedAnswer {
  id: string; question: string; module: string; sql_synced: boolean; model_name: string; owner_name: string;
  status: AnswerStatus; accuracy_percent: number; adoption_count: number; is_favorite: boolean; updated_at: string;
}
export interface AnswerSummary {
  total: number; average_accuracy: number; monthly_adoptions: number; pending_review: number;
  favorites: number; drafts: number; published: number;
}
export interface AnswerLibraryResponse { summary: AnswerSummary; items: VerifiedAnswer[]; total: number; page: number; page_size: number }
export interface AnswerInput { question: string; model_name: string; owner_name: string; module?: string; status?: 'DRAFT' | 'REVIEW' | 'PUBLISHED'; accuracy_percent?: number }

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
  kpis: DashboardKpi[]; revenue_trend: DashboardTrendPoint[]; regions: DashboardRegionRow[]; insight: string;
}

export interface EvaluationRun {
  id: string; release_name: string; model_name: string; status: string; is_current: boolean; golden_set_count: number;
  sql_generation_rate: number; result_accuracy: number; semantic_accuracy: number; relevance_accuracy: number;
  average_response_seconds: number; error_distribution: Array<{ label: string; percent: number; color: string }>;
  trend_points: Array<{ date: string; value: number }>; completed_at: string; duration_seconds: number;
}
export interface EvaluationMetric { key: string; label: string; value: number; unit: string; change: number }
export interface EvaluationOverview { current: EvaluationRun; metrics: EvaluationMetric[]; comparisons: EvaluationRun[] }

export interface QueryExecution {
  status?: 'SUCCEEDED' | 'FAILED' | 'TIMEOUT' | 'CONCURRENCY_LIMIT';
  columns?: string[]; column_types?: string[]; rows?: Array<Record<string, unknown>>;
  row_count?: number; truncated?: boolean; duration_ms?: number; normalized_sql?: string;
  result_signature?: string; error_code?: string; error_message?: string;
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
  summary: string; kpis: Array<{ label: string; value: unknown; unit?: string }>;
  recommended_questions: string[]; error_code?: string; error_message?: string;
}
