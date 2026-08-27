export type DatasourceKind = 'postgresql' | 'mysql';

export interface ModelProviderStatus {
  id: string;
  provider_id?: string;
  model_id?: string | null;
  display_name: string;
  model_name: string | null;
  configured: boolean;
  enabled?: boolean;
  active: boolean;
  healthy?: boolean | null;
  health_message?: string;
  last_checked_at?: string | null;
  capabilities?: string[];
  priority?: number;
  cost_policy?: string;
  credential_source?: 'SERVER_ENVIRONMENT' | 'NOT_REQUIRED';
  external_model: boolean;
  structured_output: boolean;
  protocol: 'openai-chat-completions' | 'local';
  base_url?: string | null;
  credential_env?: string | null;
}

export interface ModelProviderCatalog {
  active_provider: string;
  selection_strategy?: string;
  secrets_exposed: false;
  items: ModelProviderStatus[];
}
export interface QuerySecuritySettings {
  query_timeout_ms: number; max_rows: number; read_only_query: true; dangerous_sql_block: true;
  result_verification: true; sql_guard_policy: 'STRICT' | 'STANDARD'; allowed_schemas: string[]; blocked_schemas: string[];
}
export interface WorkspaceConfigSettings { workspace_name: string; default_datasource_id?: string | null; default_semantic_model_id?: string | null; status: 'ACTIVE' | 'READ_ONLY' }
export interface AppearanceSettings { product_name: string; brand_tagline: string; logo_url: string; primary_color: string; theme: 'LIGHT' | 'SYSTEM' }
export interface WorkspaceSettings {
  query_security: QuerySecuritySettings; workspace: WorkspaceConfigSettings; appearance: AppearanceSettings; version: number; updated_at?: string;
  workspace_summary: { id: string; name: string; member_count: number; roles: Record<string, number>; status: string; isolation: string; datasources: Array<{ id: string; name: string; status: string }>; semantic_models: Array<{ id: string; name: string; status: string; datasource_id: string }> };
}
export interface SystemInformation { app_version: string; git_sha: string; release_version: string; backend_health: string; frontend_build: string; database_status: string; migration_head: string; rag_status: string; sandbox_status: string; model_gateway_status: string }

export interface SecurityUser {
  id: string; email: string; display_name: string; role: 'ADMIN' | 'ANALYST'; status: string; last_active_at?: string;
}
export interface SecurityRole { name: 'ADMIN' | 'ANALYST'; permissions: string[]; user_count: number }
export interface SecurityAuditEvent {
  id: string; actor_email: string; action: string; resource_type: string; resource_id?: string;
  status: string; details: Record<string, unknown>; created_at: string;
}
export interface WorkspaceInvitation { id: string; email: string; role: 'ADMIN' | 'ANALYST'; status: string; expires_at: string; created_at: string; invite_url?: string }
export interface SecurityOverview {
  current_actor?: SecurityUser; user_count: number; role_count: number; active_user_count: number; audit_event_count: number;
  users: SecurityUser[]; roles: SecurityRole[]; audit_events: SecurityAuditEvent[]; invitations?: WorkspaceInvitation[];
}
export interface AuditPage { items: SecurityAuditEvent[]; page: number; page_size: number; total: number }

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
export interface DashboardInput { name: string; description: string; is_shared?: boolean }

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
  profile?: EvaluationProfile; accuracy?: Record<string, number>; release_gate?: Record<string, unknown>; multiple_ground_truth?: boolean;
}
export interface EvaluationProfile { model: string; prompt: string; semantic_engine: string; nl2sql_engine: string; version: string }
export interface EvaluationCreate { name: string; profile: EvaluationProfile }
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
export interface EvaluationComparison { axes: string[]; runs: EvaluationRun[]; metrics: Array<{ key: string; values: Array<{ run_id: string; value: number }> }>; winner_run_id?: string }
export interface EvaluationDashboard {
  current: EvaluationRun;
  accuracy_cards: Array<{ key: string; label: string; value: number; passed: boolean }>;
  error_analysis: Array<{ category: string; count: number }>;
  release_gate: { run_id: string; status: string; thresholds: Record<string, number>; metrics: Record<string, number>; checks: Array<{ key: string; passed: boolean }> };
  comparison_axes: string[];
}
export interface FeedbackCandidate { answer_id: string; question: string; sql: string; score: number; version: number; status: string }
export interface FeedbackWorkflow {
  answer_id: string; query_run_id?: string; status: string; workflow_state: string; question: string;
  corrected_sql?: string; oracle_status?: string; version: number; feedback: Record<string, unknown>;
  reviewer?: string; question_pattern?: string; replay_count?: number;
}
export interface FeedbackDashboard {
  terminology: Array<{
    id?: string;
    semantic_model_id?: string;
    business_key?: string;
    term: string;
    synonyms: string[];
    definition: string;
    mapped_object: string;
  }>;
  sql_examples: FeedbackCandidate[]; workflows: FeedbackWorkflow[]; total_replays: number; passed_replays: number; feedback_replay_rate: number;
}
export interface FeedbackReplay {
  candidate: FeedbackCandidate; query_run_id: string; guard_status: string; oracle_status: string;
  result_signature?: string; replay_passed: boolean; replay_rate: number;
}

export interface QueryExecution {
  status?: 'SUCCEEDED' | 'FAILED' | 'TIMEOUT' | 'CONCURRENCY_LIMIT';
  columns?: string[]; column_types?: string[]; rows?: Array<Record<string, unknown>>;
  row_count?: number; truncated?: boolean; duration_ms?: number; normalized_sql?: string;
  result_signature?: string; error_code?: string; error_message?: string;
}
export type ChartType = 'KPI' | 'LINE' | 'BAR' | 'HORIZONTAL_BAR' | 'GROUPED_BAR' | 'STACKED_BAR' | 'DONUT' | 'TABLE';
export interface ChartSpec {
  version: string; chart_type: ChartType; title: string; x_field?: string; y_fields: string[];
  series: Array<{ name: string; field: string; type: 'line' | 'bar' | 'pie' | 'kpi' | 'table'; stack?: string }>;
  aggregation: Record<string, string>; unit: Record<string, string>; field_labels?: Record<string, string>; sort: string[]; limit: number;
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

export type QuestionRoute = 'DATA_QUERY' | 'DATA_FOLLOW_UP' | 'KNOWLEDGE_QUERY' | 'HYBRID_ANALYSIS' | 'COMPLEX_ANALYSIS' | 'GENERAL_CHAT' | 'SYSTEM_CAPABILITY' | 'MODEL_STATUS' | 'ADMIN_QUERY' | 'FILE_QUERY' | 'MULTIMODAL_QUERY' | 'CLARIFICATION' | 'UNSUPPORTED';
export interface SessionUser { id: string; workspace_id: string; email: string; display_name: string; role: 'ADMIN' | 'ANALYST' }
export interface SessionResponse { authenticated: true; user: SessionUser; expires_at: string }
export interface LoginInput { email: string; password: string; remember: boolean }
export interface Conversation {
  id: string; title: string; summary: string; active_attachment_ids: string[]; project_id?: string | null;
  pinned_at?: string | null; archived_at?: string | null; created_at: string; updated_at: string;
}
export type ConversationListState = 'active' | 'archived' | 'all';
export interface ConversationListOptions { q?: string; state?: ConversationListState; project_id?: string }
export interface Project {
  id: string; name: string; description: string; archived_at?: string | null; created_at: string; updated_at: string;
}
export interface ConversationBatchResult { affected_count: number; conversation_ids: string[] }
export interface ConversationShare {
  id: string; conversation_id: string; expires_at: string; revoked_at?: string | null; access_count: number;
  last_accessed_at?: string | null; created_at: string;
}
export interface ConversationShareCreated extends ConversationShare { token: string; share_path: string }
export interface SharedConversationMessage {
  id: string; role: 'user' | 'assistant'; content: string; message_parts: Array<Record<string, unknown>>; created_at: string;
}
export interface SharedConversation {
  share_id: string; title: string; summary: string; created_at: string; updated_at: string;
  expires_at: string; read_only: true; messages: SharedConversationMessage[];
}

export type ResultSemantic = 'VALUE' | 'ZERO' | 'NO_ROWS' | 'NULL_VALUE' | 'FAILED';
export type ChatRunState = 'IDLE' | 'UPLOADING' | 'SUBMITTING' | 'RUNNING' | 'STREAMING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export interface CitationItem {
  title: string;
  version: string | number;
  locator: string;
  resource_id: string;
}

export interface TextMessagePart { type: 'text'; text: string; role?: string }
export interface KpiMessagePart {
  type: 'kpi';
  items: Array<{ label: string; value: string | number | null; unit: string }>;
}
export interface ChartMessagePart { type: 'chart'; chart_spec: ChartSpec; result_signature: string }
export interface TableMessagePart {
  type: 'table';
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  result_signature: string;
}
export interface CitationsMessagePart { type: 'citations'; items: CitationItem[] }
export interface EvidenceMessagePart {
  type: 'evidence';
  sql: string | null;
  guard: Record<string, unknown>;
  oracle: Record<string, unknown>;
  semantic: Record<string, unknown>;
  phases: Array<Record<string, unknown>>;
}
export interface ErrorMessagePart { type: 'error'; code: string; message: string; retryable: boolean }

export type MessagePart =
  | TextMessagePart
  | KpiMessagePart
  | ChartMessagePart
  | TableMessagePart
  | CitationsMessagePart
  | EvidenceMessagePart
  | ErrorMessagePart;

export interface ChatMessage {
  id: string; conversation_id: string; parent_message_id?: string; role: 'user' | 'assistant'; content: string;
  route?: QuestionRoute; status: string; attachment_ids: string[]; context_payload?: Record<string, unknown>; response_payload: Record<string, unknown>;
  trace_payload: Record<string, unknown>; error_code?: string; created_at: string;
  message_parts?: MessagePart[]; result_semantic?: ResultSemantic;
}
export interface ConversationDetail extends Conversation { messages: ChatMessage[] }
export interface ChatInput {
  conversation_id: string; content: string; parent_message_id?: string; client_message_id: string;
  attachment_ids: string[]; route?: QuestionRoute; datasource_id?: string; semantic_model_id?: string;
}
export interface ChatResponse {
  conversation: Conversation;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  message_parts?: MessagePart[];
  result_semantic?: ResultSemantic;
}

export type ChatPublicPhase =
  | 'understanding'
  | 'semantic_mapping'
  | 'querying_data'
  | 'retrieving_knowledge'
  | 'verifying'
  | 'composing_answer';

export type ChatStreamEventType =
  | 'run.started'
  | 'phase.started'
  | 'phase.completed'
  | 'answer.delta'
  | 'artifact.ready'
  | 'citations.ready'
  | 'run.completed'
  | 'run.failed'
  | 'run.cancelled'
  | 'heartbeat';

export interface ChatStreamEnvelope<T extends ChatStreamEventType> {
  seq: number;
  run_id: string;
  conversation_id: string;
  message_id: string;
  timestamp: string;
  event_type: T;
}

export interface ChatRunStartedEvent extends ChatStreamEnvelope<'run.started'> {
  route?: QuestionRoute;
  capabilities?: string[];
}
export interface ChatPhaseEvent extends ChatStreamEnvelope<'phase.started' | 'phase.completed'> {
  phase: ChatPublicPhase;
  label: string;
  duration_ms?: number;
  metadata?: Record<string, unknown>;
}
export interface ChatAnswerDeltaEvent extends ChatStreamEnvelope<'answer.delta'> { delta: string }
export interface ChatArtifactReadyEvent extends ChatStreamEnvelope<'artifact.ready'> {
  artifact_type: 'kpi' | 'chart' | 'table' | 'file' | 'evidence' | string;
  artifact: MessagePart | Record<string, unknown>;
}
export interface ChatCitationsReadyEvent extends ChatStreamEnvelope<'citations.ready'> { citations: CitationItem[] }
export interface ChatRunCompletedEvent extends ChatStreamEnvelope<'run.completed'> {
  status: 'SUCCEEDED' | 'PARTIAL';
  result_semantic: ResultSemantic;
  message_parts: MessagePart[];
  response: ChatResponse;
}
export interface ChatRunFailedEvent extends ChatStreamEnvelope<'run.failed'> {
  code: string;
  message: string;
  retryable: boolean;
}
export interface ChatRunCancelledEvent extends ChatStreamEnvelope<'run.cancelled'> {
  code: 'RUN_CANCELLED';
  message?: string;
}
export interface ChatHeartbeatEvent extends ChatStreamEnvelope<'heartbeat'> {}

export type ChatStreamEvent =
  | ChatRunStartedEvent
  | ChatPhaseEvent
  | ChatAnswerDeltaEvent
  | ChatArtifactReadyEvent
  | ChatCitationsReadyEvent
  | ChatRunCompletedEvent
  | ChatRunFailedEvent
  | ChatRunCancelledEvent
  | ChatHeartbeatEvent;

export interface ChatStreamHandlers {
  onEvent?: (event: ChatStreamEvent) => void;
  onDelta?: (delta: string, event: ChatStreamEvent) => void;
  onStateChange?: (state: ChatRunState, event?: ChatStreamEvent) => void;
}
export interface Attachment {
  id: string; conversation_id: string; filename: string; extension: string; mime_type: string; kind: 'STRUCTURED' | 'DOCUMENT' | 'IMAGE' | 'UNKNOWN';
  size_bytes: number; status: 'PROCESSING' | 'READY' | 'FAILED'; error_code?: string; created_at: string; expires_at: string;
}
