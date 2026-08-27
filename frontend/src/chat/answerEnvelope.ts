import type { ChatMessage, ChatResponse, ChartSpec, ResultSemantic } from '../types/api';

export type AnswerRoute =
  | 'DATA_QUERY'
  | 'DATA_FOLLOW_UP'
  | 'KNOWLEDGE_QUERY'
  | 'HYBRID_ANALYSIS'
  | 'COMPLEX_ANALYSIS'
  | 'FILE_QUERY'
  | 'VISION_QUERY'
  | 'GENERAL_CHAT'
  | 'SYSTEM_CAPABILITY'
  | 'MODEL_STATUS'
  | 'ADMIN_QUERY'
  | 'CLARIFICATION'
  | 'UNSUPPORTED';

export interface AnswerKpi { label: string; value: unknown; unit: string }
export interface AnswerTable {
  columns: string[];
  column_labels?: Record<string, string>;
  rows: Array<Record<string, unknown>>;
  row_count: number;
  result_signature?: string;
  truncated: boolean;
}
export interface AnswerCitation {
  id: string;
  title: string;
  version: string;
  locator: string;
  resource_id: string;
  href?: string;
}
export interface AnswerArtifact {
  id: string;
  name: string;
  kind: string;
  media_type?: string;
  download_url: string;
  size_bytes?: number;
}
export interface FileEvidenceItem {
  attachment_id: string;
  filename: string;
  kind: string;
  locator?: string;
  result_signature?: string;
}
export interface VisualClaimItem {
  claim: string;
  value: unknown;
  locator?: string;
  confidence?: number;
  time_range?: string;
  dimension?: string;
}
export interface VisualEvidenceItem {
  attachment_id?: string;
  provider?: string;
  model?: string;
  claims: VisualClaimItem[];
  sanitized_text: string;
  sensitive_classification: string;
  injection_detected: boolean;
  signature?: string;
}
export interface AgentStepItem {
  ordinal: number;
  code: string;
  agent_role: string;
  tool_name?: string;
  status: string;
  duration_ms: number;
  result_signature?: string;
  error_code?: string;
}
export interface AnswerWarning { code: string; message: string; severity: string }
export interface AnswerError { code: string; message: string; retryable: boolean }
export interface VerificationCheck { code: string; passed?: boolean; detail?: string }
export interface AnswerVerification { status: string; checks: VerificationCheck[]; result_signature?: string }
export interface AnswerCost {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  amount_cny: number;
  exact: boolean;
  pricing_version?: string;
}
export interface AnswerLatency { total_ms: number; model_ms?: number; time_to_first_token_ms?: number }

export interface AnswerEnvelope {
  version: string;
  answer_id: string;
  conversation_id: string;
  message_id: string;
  source_question_id?: string;
  request_id?: string;
  workspace_id?: string;
  trace_id: string;
  route: AnswerRoute;
  status: string;
  result_semantic: ResultSemantic;
  summary: string;
  markdown: string;
  kpis: AnswerKpi[];
  insights: string[];
  sql?: string;
  table?: AnswerTable;
  chart?: ChartSpec;
  citations: AnswerCitation[];
  artifacts: AnswerArtifact[];
  file_evidence: FileEvidenceItem[];
  visual_evidence: VisualEvidenceItem[];
  agent_steps: AgentStepItem[];
  warnings: AnswerWarning[];
  errors: AnswerError[];
  cost: AnswerCost;
  latency: AnswerLatency;
  provider?: string;
  model?: string;
  verification: AnswerVerification;
  follow_up_suggestions: string[];
}

type JsonRecord = Record<string, unknown>;
type PublicPart = { type: string; [key: string]: unknown };

const ROUTES = new Set<AnswerRoute>([
  'DATA_QUERY', 'DATA_FOLLOW_UP', 'KNOWLEDGE_QUERY', 'HYBRID_ANALYSIS', 'COMPLEX_ANALYSIS',
  'FILE_QUERY', 'VISION_QUERY', 'GENERAL_CHAT', 'SYSTEM_CAPABILITY', 'MODEL_STATUS', 'ADMIN_QUERY',
  'CLARIFICATION', 'UNSUPPORTED',
]);
const SEMANTICS = new Set<ResultSemantic>(['VALUE', 'ZERO', 'NO_ROWS', 'NULL_VALUE', 'FAILED']);
const CHART_TYPES = new Set(['KPI', 'LINE', 'BAR', 'HORIZONTAL_BAR', 'GROUPED_BAR', 'STACKED_BAR', 'DONUT', 'TABLE']);
const SERIES_TYPES = new Set(['line', 'bar', 'pie', 'kpi', 'table']);

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function record(value: unknown): JsonRecord {
  return isRecord(value) ? value : {};
}

function records(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function text(value: unknown, limit = 100_000): string {
  if (typeof value !== 'string' && typeof value !== 'number') return '';
  return String(value).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, ' ').trim().slice(0, limit);
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function optionalNumber(value: unknown): number | undefined {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function filename(value: unknown): string {
  return (text(value, 512).split(/[\\/]/).at(-1) ?? '').replace(/\s+/g, ' ').trim() || 'artifact';
}

function locatorText(value: unknown): string | undefined {
  const direct = text(value, 512);
  if (direct) return direct;
  const source = record(value);
  const labels: Array<[string, string]> = [
    ['locator_type', 'type'], ['page', 'page'], ['paragraph', 'paragraph'],
    ['table', 'table'], ['row', 'row'], ['column', 'column'], ['tile', 'tile'],
  ];
  const parts = labels.flatMap(([key, label]) => {
    const item = text(source[key], 128);
    return item ? [`${label}:${item}`] : [];
  });
  return parts.join(' · ').slice(0, 512) || undefined;
}

function normalizeRoute(value: unknown): AnswerRoute {
  const candidate = text(value, 64).toUpperCase();
  if (candidate === 'MULTIMODAL_QUERY') return 'VISION_QUERY';
  return ROUTES.has(candidate as AnswerRoute) ? candidate as AnswerRoute : 'UNSUPPORTED';
}

function normalizeSemantic(value: unknown, status: string): ResultSemantic {
  const candidate = text(value, 32).toUpperCase();
  if (SEMANTICS.has(candidate as ResultSemantic)) return candidate as ResultSemantic;
  return status === 'SUCCEEDED' || status === 'PARTIAL' ? 'VALUE' : 'FAILED';
}

export function safeCitationHref(value: unknown): string | undefined {
  const candidate = text(value, 2_048);
  if (candidate.startsWith('/api/v1/') && !candidate.includes('\\') && !candidate.includes('..') && !/\s/.test(candidate)) return candidate;
  if (/^https?:\/\//i.test(candidate)) return candidate;
  return undefined;
}

export function safeArtifactUrl(value: unknown): string | undefined {
  const candidate = text(value, 2_048);
  if (!candidate.startsWith('/api/v1/') || candidate.includes('\\') || candidate.includes('..') || /\s/.test(candidate)) return undefined;
  return candidate;
}

function stringMap(value: unknown): Record<string, string> {
  return Object.fromEntries(Object.entries(record(value))
    .map(([key, item]) => [text(key, 256), text(item, 256)])
    .filter(([key, item]) => Boolean(key && item)));
}

function normalizeChart(value: unknown, table?: AnswerTable): ChartSpec | undefined {
  const source = record(value);
  const rawType = text(source.chart_type, 32).toUpperCase();
  const chartType = rawType === 'PIE' ? 'DONUT' : rawType;
  if (!CHART_TYPES.has(chartType)) return undefined;
  const xField = text(source.x_field ?? source.x, 256) || undefined;
  const rawYFields = Array.isArray(source.y_fields) ? source.y_fields : [source.y];
  const yFields = [...new Set(rawYFields.map((item) => text(item, 256)).filter(Boolean))].slice(0, 20);
  if (!yFields.length && chartType !== 'TABLE') return undefined;
  const series = records(source.series)
    .map((item) => {
      const field = text(item.field, 256);
      const type = text(item.type, 32).toLowerCase();
      if (!field || !SERIES_TYPES.has(type)) return undefined;
      const stack = text(item.stack, 128) || undefined;
      return { name: text(item.name ?? field, 256), field, type: type as 'line' | 'bar' | 'pie' | 'kpi' | 'table', ...(stack ? { stack } : {}) };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));
  if (!series.length) {
    const type = chartType === 'LINE' ? 'line' : chartType === 'DONUT' ? 'pie' : 'bar';
    series.push(...yFields.map((field) => ({ name: field, field, type } as const)));
  }
  const legend = record(source.legend);
  const boundColumns = (Array.isArray(source.bound_columns) ? source.bound_columns : table?.columns ?? [])
    .map((item) => text(item, 256)).filter(Boolean).slice(0, 200);
  return {
    version: text(source.version, 64) || 'answer-envelope-v1',
    chart_type: chartType as ChartSpec['chart_type'],
    title: text(source.title, 512) || '分析图表',
    x_field: xField,
    y_fields: yFields,
    series,
    aggregation: stringMap(source.aggregation),
    unit: stringMap(source.unit),
    field_labels: stringMap(source.field_labels),
    sort: (Array.isArray(source.sort) ? source.sort : []).map((item) => text(item, 256)).filter(Boolean).slice(0, 20),
    limit: Math.min(500, Math.max(1, numberValue(source.limit, 20))),
    legend: { show: legend.show !== false },
    axis: {},
    tooltip: {},
    data_source_query_id: text(source.data_source_query_id, 256) || 'answer-envelope',
    result_signature: text(source.result_signature ?? table?.result_signature, 256) || undefined,
    bound_columns: boundColumns,
    bound_row_count: numberValue(source.bound_row_count, table?.row_count ?? 0),
    null_policy: text(source.null_policy, 64) || 'PRESERVE',
    warnings: (Array.isArray(source.warnings) ? source.warnings : []).map((item) => text(item, 2_000)).filter(Boolean).slice(0, 100),
  };
}

function normalizeTable(value: unknown): AnswerTable | undefined {
  const source = record(value);
  const sourceRows = records(source.rows);
  const columns = [...new Set((Array.isArray(source.columns) ? source.columns : Object.keys(sourceRows[0] ?? {}))
    .map((item) => text(item, 256)).filter(Boolean))].slice(0, 200);
  if (!columns.length && !sourceRows.length) return undefined;
  const rows = sourceRows.slice(0, 500).map((row) => Object.fromEntries(columns.map((column) => [column, row[column]])));
  const rowCount = numberValue(source.row_count, rows.length);
  return {
    columns,
    column_labels: Object.fromEntries(columns.map((column) => [column, stringMap(source.column_labels)[column] || column])),
    rows,
    row_count: Math.max(rowCount, rows.length),
    result_signature: text(source.result_signature, 256) || undefined,
    truncated: Boolean(source.truncated) || rowCount > rows.length,
  };
}

function messageParts(message: ChatMessage): PublicPart[] {
  const extended = message as ChatMessage & { message_parts?: unknown };
  const payload = record(message.response_payload);
  const source = extended.message_parts ?? payload.message_parts ?? payload.parts;
  return records(source)
    .map((part) => ({ ...part, type: text(part.type, 64) }))
    .filter((part) => Boolean(part.type));
}

function firstPart(parts: PublicPart[], type: string): JsonRecord {
  return record(parts.find((part) => part.type === type));
}

function findQuery(value: unknown, depth = 0): JsonRecord | undefined {
  if (!isRecord(value) || depth > 6) return undefined;
  if (isRecord(value.execution)) return value;
  for (const key of ['data', 'data_evidence', 'primary', 'analysis', 'query']) {
    const found = findQuery(value[key], depth + 1);
    if (found) return found;
  }
  return undefined;
}

function normalizeKpis(value: unknown): AnswerKpi[] {
  const seen = new Set<string>();
  return records(value).flatMap((item) => {
    const label = text(item.label, 160);
    if (!label || seen.has(label)) return [];
    seen.add(label);
    return [{ label, value: item.value, unit: text(item.unit, 40) }];
  }).slice(0, 100);
}

function normalizeCitations(value: unknown): AnswerCitation[] {
  const seen = new Set<string>();
  return records(value).flatMap((item, index) => {
    const resourceId = text(item.resource_id ?? item.document_id ?? item.attachment_id ?? item.chunk_id, 256);
    const title = filename(item.title ?? item.filename ?? '业务资料');
    const version = text(item.version ?? item.document_version_id ?? item.attachment_id, 256);
    const locator = locatorText(item.locator) ?? text(item.chunk_id ?? resourceId, 512);
    if (!resourceId || !title || !version || !locator) return [];
    const key = `${resourceId}\u0000${version}\u0000${locator}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{
      id: text(item.id ?? item.citation_id, 256) || `citation-${index}-${resourceId}`,
      title, version, locator, resource_id: resourceId,
      href: safeCitationHref(item.href ?? item.url),
    }];
  }).slice(0, 200);
}

function normalizeArtifacts(value: unknown): AnswerArtifact[] {
  const seen = new Set<string>();
  return records(value).flatMap((item) => {
    const url = safeArtifactUrl(item.download_url ?? item.url);
    const id = text(item.id, 256);
    if (!url || !id || seen.has(`${id}\u0000${url}`)) return [];
    seen.add(`${id}\u0000${url}`);
    const size = optionalNumber(item.size_bytes);
    return [{
      id,
      name: filename(item.name ?? id),
      kind: text(item.kind, 64) || 'FILE',
      media_type: text(item.media_type, 128) || undefined,
      download_url: url,
      size_bytes: size,
    }];
  }).slice(0, 100);
}

function normalizeFileEvidence(value: unknown): FileEvidenceItem[] {
  const seen = new Set<string>();
  return records(value).flatMap((item) => {
    const attachmentId = text(item.attachment_id, 256);
    if (!attachmentId || seen.has(attachmentId)) return [];
    seen.add(attachmentId);
    return [{
      attachment_id: attachmentId,
      filename: filename(item.filename ?? attachmentId),
      kind: text(item.kind, 64) || 'FILE',
      locator: text(item.locator, 512) || undefined,
      result_signature: text(item.result_signature, 256) || undefined,
    }];
  }).slice(0, 100);
}

function normalizeVisualEvidence(value: unknown): VisualEvidenceItem[] {
  return records(value).map((item) => ({
    attachment_id: text(item.attachment_id, 256) || undefined,
    provider: text(item.provider, 128) || undefined,
    model: text(item.model, 256) || undefined,
    claims: records(item.claims).flatMap((claim) => {
      const name = text(claim.claim ?? claim.metric, 512);
      if (!name) return [];
      const confidence = optionalNumber(claim.confidence);
      return [{
        claim: name,
        value: claim.value,
        locator: locatorText(claim.locator),
        confidence: confidence !== undefined && confidence <= 1 ? confidence : undefined,
        time_range: text(claim.time_range, 256) || undefined,
        dimension: text(claim.dimension, 256) || undefined,
      }];
    }).slice(0, 100),
    sanitized_text: text(item.sanitized_text, 40_000),
    sensitive_classification: text(item.sensitive_classification, 32) || 'NONE',
    injection_detected: Boolean(item.injection_detected),
    signature: text(item.signature, 256) || undefined,
  })).slice(0, 50);
}

function normalizeAgentSteps(value: unknown): AgentStepItem[] {
  return records(value).flatMap((item, index) => {
    const code = text(item.code, 128);
    const role = text(item.agent_role, 128);
    const status = text(item.status, 64);
    if (!code || !role || !status) return [];
    return [{
      ordinal: Math.max(1, numberValue(item.ordinal, index + 1)),
      code,
      agent_role: role,
      tool_name: text(item.tool_name, 128) || undefined,
      status,
      duration_ms: numberValue(item.duration_ms),
      result_signature: text(item.result_signature, 256) || undefined,
      error_code: text(item.error_code, 128) || undefined,
    }];
  }).slice(0, 100);
}

function normalizeWarnings(value: unknown): AnswerWarning[] {
  const seen = new Set<string>();
  return records(value).flatMap((item) => {
    const code = text(item.code, 128) || 'ANSWER_WARNING';
    const message = text(item.message, 2_000);
    const key = `${code}\u0000${message}`;
    if (!message || seen.has(key)) return [];
    seen.add(key);
    return [{ code, message, severity: text(item.severity, 32) || 'WARNING' }];
  }).slice(0, 100);
}

function normalizeErrors(value: unknown): AnswerError[] {
  const seen = new Set<string>();
  return records(value).flatMap((item) => {
    const code = text(item.code, 128) || 'CHAT_RUN_FAILED';
    const message = text(item.message, 2_000);
    const key = `${code}\u0000${message}`;
    if (!message || seen.has(key)) return [];
    seen.add(key);
    return [{ code, message, retryable: Boolean(item.retryable) }];
  }).slice(0, 100);
}

function normalizeVerification(value: unknown): AnswerVerification {
  const source = record(value);
  return {
    status: text(source.status, 64) || 'NOT_RUN',
    checks: records(source.checks).flatMap((item) => {
      const code = text(item.code, 128);
      if (!code) return [];
      return [{ code, passed: typeof item.passed === 'boolean' ? item.passed : undefined, detail: text(item.detail, 1_000) || undefined }];
    }).slice(0, 100),
    result_signature: text(source.result_signature, 256) || undefined,
  };
}

function legacyVerification(query: JsonRecord | undefined, payload: JsonRecord, visual: VisualEvidenceItem[], resultSignature?: string): AnswerVerification {
  const checks: VerificationCheck[] = [];
  if (query) {
    const guard = record(query.guard);
    if (typeof guard.allowed === 'boolean') checks.push({ code: 'SQL_GUARD', passed: guard.allowed, detail: '只读 SQL 安全校验' });
    const oracleStatus = text(record(query.oracle).status, 64).toUpperCase();
    if (oracleStatus) checks.push({ code: 'RESULT_ORACLE', passed: oracleStatus === 'PASSED', detail: oracleStatus });
  }
  const grounded = record(payload.grounded_answer_guard);
  if (typeof grounded.passed === 'boolean') checks.push({
    code: 'CITATION_ANSWER_GUARD',
    passed: grounded.passed,
    detail: text(grounded.reason, 1_000) || '引用与回答绑定校验',
  });
  visual.forEach((item) => checks.push({ code: 'VISUAL_EVIDENCE_SAFETY', passed: !item.injection_detected, detail: item.signature ?? '签名视觉证据' }));
  const status = checks.some((check) => check.passed === false)
    ? 'FAILED'
    : checks.length && checks.every((check) => check.passed === true)
      ? 'VERIFIED'
      : checks.length
        ? 'PARTIAL'
        : 'NOT_RUN';
  return { status, checks, result_signature: resultSignature };
}

function legacyEnvelope(message: ChatMessage): AnswerEnvelope {
  const payload = record(message.response_payload);
  const trace = record(message.trace_payload);
  const parts = messageParts(message);
  const query = findQuery(payload);
  const tableSource = firstPart(parts, 'table');
  const fileAnalysis = record(payload.file_analysis);
  const table = normalizeTable(
    Object.keys(tableSource).length
      ? tableSource
      : Object.keys(fileAnalysis).length
        ? fileAnalysis.result
        : query?.execution,
  );
  const chartPart = firstPart(parts, 'chart');
  const chart = normalizeChart(chartPart.chart_spec ?? query?.chart_spec ?? fileAnalysis.chart, table);
  const citationParts = parts.filter((part) => part.type === 'citations').flatMap((part) => records(part.items));
  const primary = record(record(payload.analysis).primary);
  const knowledge = record(primary.knowledge ?? primary.knowledge_evidence);
  const citationSource = citationParts.length ? citationParts : records(payload.citations).concat(records(knowledge.citations));
  const artifactItems = records(fileAnalysis.artifacts).flatMap((item) => {
    const attachmentId = text(item.attachment_id, 256) || 'artifact';
    return [
      item.csv_url ? { id: `${attachmentId}:csv`, name: '下载 CSV Artifact', kind: 'CSV', media_type: 'text/csv', download_url: item.csv_url } : undefined,
      item.json_url ? { id: `${attachmentId}:json`, name: '下载 JSON Artifact', kind: 'JSON', media_type: 'application/json', download_url: item.json_url } : undefined,
    ].filter(isRecord);
  });
  const status = text(query?.status ?? message.status, 64) || 'FAILED';
  const execution = record(query?.execution);
  const rows = Array.isArray(execution.rows) ? execution.rows : undefined;
  const semantic = status === 'SECURITY_REJECTED' || status === 'ORACLE_MISMATCH'
    ? 'FAILED'
    : execution.status === 'SUCCEEDED' && rows?.length === 0
      ? 'NO_ROWS'
      : normalizeSemantic(payload.result_semantic, status);
  const conclusion = parts.find((part) => part.type === 'text' && (part.role === 'conclusion' || !part.role));
  const narrative = record(query?.narrative);
  const evidence = firstPart(parts, 'evidence');
  const followups = parts.filter((part) => part.type === 'text' && part.role === 'followups')
    .flatMap((part) => text(part.text).split('\n')).map((item) => text(item, 1_000)).filter(Boolean);
  const insights = parts.filter((part) => part.type === 'text' && part.role === 'insights')
    .flatMap((part) => text(part.text).split('\n')).map((item) => text(item, 2_000)).filter(Boolean);
  const modelCall = record(trace.model_call);
  const usage = record(modelCall.usage);
  const partErrors = parts.filter((part) => part.type === 'error');
  const visualEvidence = normalizeVisualEvidence(payload.visual_evidence);
  return {
    version: '1.0',
    answer_id: message.id,
    conversation_id: message.conversation_id,
    message_id: message.id,
    source_question_id: message.parent_message_id ?? message.id,
    request_id: text(trace.request_id, 256) || message.parent_message_id || message.id,
    workspace_id: text(trace.workspace_id, 256) || 'unknown',
    trace_id: text(trace.trace_id, 256) || `message-${message.id}`,
    route: normalizeRoute(message.route),
    status,
    result_semantic: semantic,
    summary: text(conclusion?.text ?? narrative.conclusion, 20_000) || message.content,
    markdown: message.content,
    kpis: normalizeKpis(
      parts.filter((part) => part.type === 'kpi').flatMap((part) => records(part.items)).length
        ? parts.filter((part) => part.type === 'kpi').flatMap((part) => records(part.items))
        : records(query?.kpis).concat(records(narrative.key_metrics)),
    ),
    insights: [...new Set(insights.length ? insights : (Array.isArray(narrative.insights) ? narrative.insights.map((item) => text(item)).filter(Boolean) : []))],
    sql: text(evidence.sql ?? record(query?.guard).normalized_sql ?? record(query?.plan).generated_sql, 100_000) || undefined,
    table,
    chart,
    citations: normalizeCitations(citationSource),
    artifacts: normalizeArtifacts(artifactItems),
    file_evidence: normalizeFileEvidence(payload.citations),
    visual_evidence: visualEvidence,
    agent_steps: normalizeAgentSteps(primary.steps),
    warnings: [],
    errors: normalizeErrors(partErrors.length ? partErrors : status === 'SUCCEEDED' || status === 'PARTIAL' ? [] : [{ code: message.error_code ?? status, message: text(query?.error_message) || message.content, retryable: true }]),
    cost: {
      input_tokens: numberValue(usage.input_tokens),
      cached_input_tokens: numberValue(usage.cached_input_tokens),
      output_tokens: numberValue(usage.output_tokens),
      total_tokens: numberValue(usage.total_tokens),
      amount_cny: numberValue(modelCall.cost_cny),
      exact: Boolean(usage.exact),
      pricing_version: text(modelCall.pricing_version, 128) || undefined,
    },
    latency: {
      total_ms: numberValue(trace.elapsed_ms),
      model_ms: optionalNumber(modelCall.latency_ms),
      time_to_first_token_ms: optionalNumber(modelCall.time_to_first_token_ms),
    },
    provider: text(trace.model_provider ?? modelCall.resolved_provider, 128) || undefined,
    model: text(trace.model_name ?? modelCall.resolved_model, 256) || undefined,
    verification: legacyVerification(query, payload, visualEvidence, table?.result_signature),
    follow_up_suggestions: [...new Set(followups.length ? followups : (Array.isArray(query?.recommended_questions) ? query.recommended_questions.map((item) => text(item)).filter(Boolean) : []))].slice(0, 20),
  };
}

function normalizeCandidate(message: ChatMessage, value: unknown): AnswerEnvelope {
  const fallback = legacyEnvelope(message);
  const source = record(value);
  if (!Object.keys(source).length) return fallback;
  const status = text(source.status, 64) || fallback.status;
  const table = normalizeTable(source.table) ?? fallback.table;
  const chart = normalizeChart(source.chart, table) ?? fallback.chart;
  return {
    version: text(source.version, 64) || '1.0',
    answer_id: text(source.answer_id, 256) || fallback.answer_id,
    conversation_id: text(source.conversation_id, 256) || fallback.conversation_id,
    message_id: text(source.message_id, 256) || fallback.message_id,
    source_question_id: text(source.source_question_id, 256) || fallback.source_question_id,
    request_id: text(source.request_id, 256) || fallback.request_id,
    workspace_id: text(source.workspace_id, 256) || fallback.workspace_id,
    trace_id: text(source.trace_id, 256) || fallback.trace_id,
    route: normalizeRoute(source.route ?? fallback.route),
    status,
    result_semantic: normalizeSemantic(source.result_semantic, status),
    summary: text(source.summary, 20_000) || fallback.summary,
    markdown: text(source.markdown, 100_000) || fallback.markdown,
    kpis: normalizeKpis(source.kpis),
    insights: Array.isArray(source.insights) ? [...new Set(source.insights.map((item) => text(item, 2_000)).filter(Boolean))].slice(0, 100) : [],
    sql: text(source.sql, 100_000) || undefined,
    table,
    chart,
    citations: normalizeCitations(source.citations),
    artifacts: normalizeArtifacts(source.artifacts),
    file_evidence: normalizeFileEvidence(source.file_evidence),
    visual_evidence: normalizeVisualEvidence(source.visual_evidence),
    agent_steps: normalizeAgentSteps(source.agent_steps),
    warnings: normalizeWarnings(source.warnings),
    errors: normalizeErrors(source.errors),
    cost: {
      input_tokens: numberValue(record(source.cost).input_tokens),
      cached_input_tokens: numberValue(record(source.cost).cached_input_tokens),
      output_tokens: numberValue(record(source.cost).output_tokens),
      total_tokens: numberValue(record(source.cost).total_tokens),
      amount_cny: numberValue(record(source.cost).amount_cny),
      exact: Boolean(record(source.cost).exact),
      pricing_version: text(record(source.cost).pricing_version, 128) || undefined,
    },
    latency: {
      total_ms: numberValue(record(source.latency).total_ms),
      model_ms: optionalNumber(record(source.latency).model_ms),
      time_to_first_token_ms: optionalNumber(record(source.latency).time_to_first_token_ms),
    },
    provider: text(source.provider, 128) || undefined,
    model: text(source.model, 256) || undefined,
    verification: normalizeVerification(source.verification),
    follow_up_suggestions: Array.isArray(source.follow_up_suggestions)
      ? [...new Set(source.follow_up_suggestions.map((item) => text(item, 1_000)).filter(Boolean))].slice(0, 20)
      : [],
  };
}

export function normalizeAnswerEnvelope(message: ChatMessage, candidate?: unknown): AnswerEnvelope {
  const payload = record(message.response_payload);
  return normalizeCandidate(message, candidate ?? payload.answer_envelope);
}

export function answerEnvelopeFromResponse(response: ChatResponse): AnswerEnvelope {
  const extended = response as ChatResponse & { answer_envelope?: unknown };
  return normalizeAnswerEnvelope(response.assistant_message, extended.answer_envelope);
}

function stablePartKey(part: PublicPart): string {
  if (part.type === 'citations') {
    return `citations:${normalizeCitations(part.items).map((item) => `${item.resource_id}:${item.version}:${item.locator}`).join('|')}`;
  }
  if (part.type === 'artifact') {
    const artifact = normalizeArtifacts([part])[0];
    return artifact ? `artifact:${artifact.id}:${artifact.download_url}` : 'artifact:invalid';
  }
  if (part.type === 'table') return `table:${text(part.result_signature, 256)}`;
  if (part.type === 'chart') return `chart:${text(part.result_signature, 256)}:${text(record(part.chart_spec).chart_type, 32)}`;
  return `${part.type}:${text(part.code ?? part.role ?? part.text, 512)}`;
}

export function mergeUniqueAnswerParts(current: PublicPart[], incoming: PublicPart[]): PublicPart[] {
  const result: PublicPart[] = [];
  const seen = new Set<string>();
  for (const part of [...current, ...incoming]) {
    const key = stablePartKey(part);
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(part);
  }
  return result;
}

export function mergeFinalResponseMessages(current: ChatMessage[], response: ChatResponse): ChatMessage[] {
  const extended = response as ChatResponse & { answer_envelope?: unknown };
  const assistant = extended.answer_envelope
    ? {
        ...response.assistant_message,
        response_payload: { ...response.assistant_message.response_payload, answer_envelope: extended.answer_envelope },
      }
    : response.assistant_message;
  const finalIds = new Set([response.user_message.id, assistant.id]);
  const merged = [...current.filter((message) => !finalIds.has(message.id)), response.user_message, assistant];
  const byId = new Map<string, ChatMessage>();
  merged.forEach((message) => byId.set(message.id, message));
  return [...byId.values()];
}
