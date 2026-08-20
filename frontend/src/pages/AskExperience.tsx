import {
  ClipboardEvent,
  DragEvent,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useLocation } from 'react-router-dom';
import { chatApi } from '../api/chat';
import { queryApi } from '../api/queries';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import { EChart } from '../components/EChart';
import type {
  Attachment,
  ChartSpec,
  ChatInput,
  ChatMessage,
  ChatResponse,
  Conversation,
  ConversationDetail,
  Narrative,
  QueryResponse,
} from '../types/api';
import { ConversationSidebar, isVisibleConversation } from './chat-ui/ConversationSidebar';
import { EvidenceDrawer, type EvidenceDrawerData, type PublicCitation } from './chat-ui/EvidenceDrawer';
import './ask.css';

const prompts = [
  ['销', '统计全部订单收入', '收入、订单数、利润等关键指标'],
  ['区', '按地区统计订单收入', '区域对比与经营分布'],
  ['客', '按客户统计订单量前5名', '客户贡献与订单排行'],
  ['品', '按品类统计订单利润前4名', '品类表现与利润结构'],
] as const;

type ResultSemantic = 'VALUE' | 'ZERO' | 'NO_ROWS' | 'NULL_VALUE' | 'FAILED';
type RunStatus = 'SUBMITTING' | 'RUNNING' | 'STREAMING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
type UiPart = { type: string; [key: string]: unknown };

interface ChatStreamEvent {
  seq?: number;
  event_type: string;
  phase?: string;
  label?: string;
  delta?: string;
  artifact_type?: string;
  artifact?: Record<string, unknown>;
  citations?: Array<Record<string, unknown>>;
  message_parts?: UiPart[];
  result_semantic?: ResultSemantic;
  code?: string;
  message?: string;
  retryable?: boolean;
  response?: ChatResponse;
}

interface StreamHandlers {
  onEvent?: (event: ChatStreamEvent) => void;
  onDelta?: (delta: string, event: ChatStreamEvent) => void;
  onStateChange?: (state: string, event?: ChatStreamEvent) => void;
}

interface UiChatApi {
  stream: (input: ChatInput, handlers: StreamHandlers, signal: AbortSignal) => Promise<ChatResponse>;
  renameConversation: (id: string, title: string) => Promise<Conversation>;
}

interface PendingTurn {
  runId: string;
  conversationId: string;
  user: ChatMessage;
  content: string;
  parts: UiPart[];
  stage: string;
  status: RunStatus;
  semantic?: ResultSemantic;
  error?: string;
}

interface UploadState { id: string; name: string; progress: number; error?: string; file: File }

const streamingApi = chatApi as unknown as UiChatApi;

const PUBLIC_PHASES: Record<string, string> = {
  understanding: '正在理解问题……',
  semantic_mapping: '正在识别指标和维度……',
  querying_data: '正在查询数据……',
  retrieving_knowledge: '正在检索业务规则……',
  verifying: '正在校验结果……',
  composing_answer: '正在整理回答……',
};

function formatValue(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  return value == null ? '—' : String(value);
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function messageParts(message: ChatMessage): UiPart[] {
  const extended = message as ChatMessage & { message_parts?: UiPart[] };
  if (Array.isArray(extended.message_parts)) return extended.message_parts;
  const payload = record(message.response_payload);
  const parts = payload.message_parts ?? payload.parts;
  return Array.isArray(parts) ? parts.filter((part): part is UiPart => Boolean(part && typeof part === 'object' && 'type' in part)) : [];
}

function queryFromMessage(message: ChatMessage): QueryResponse | null {
  const analysis = record(message.response_payload.analysis);
  let primary = record(analysis.primary);
  if (message.route === 'HYBRID_ANALYSIS' && primary.data) primary = record(primary.data);
  if (typeof primary.id === 'string' && primary.execution && typeof primary.execution === 'object') return primary as unknown as QueryResponse;
  return null;
}

function explicitSemantic(message: ChatMessage): ResultSemantic | undefined {
  const extended = message as ChatMessage & { result_semantic?: ResultSemantic };
  const value = extended.result_semantic ?? record(message.response_payload).result_semantic;
  return ['VALUE', 'ZERO', 'NO_ROWS', 'NULL_VALUE', 'FAILED'].includes(String(value)) ? value as ResultSemantic : undefined;
}

function inferSemantic(message: ChatMessage, result: QueryResponse | null): ResultSemantic {
  const explicit = explicitSemantic(message);
  if (explicit) return explicit;
  if (message.status === 'FAILED' || message.status === 'REFUSED' || result?.status === 'FAILED' || result?.status === 'SECURITY_REJECTED' || result?.status === 'ORACLE_MISMATCH') return 'FAILED';
  if (!result) return 'VALUE';
  const rows = result.execution.rows ?? [];
  if ((result.execution.row_count ?? rows.length) === 0) return 'NO_ROWS';
  const primaryColumn = (result.execution.columns ?? [])[1] ?? (result.execution.columns ?? [])[0];
  const primaryValue = result.kpis[0]?.value ?? (rows[0] && primaryColumn ? rows[0][primaryColumn] : undefined);
  if (primaryValue === null) return 'NULL_VALUE';
  if (typeof primaryValue === 'number' && primaryValue === 0) return 'ZERO';
  return 'VALUE';
}

function citationsFromMessage(message: ChatMessage, parts = messageParts(message)): PublicCitation[] {
  const fromParts = parts
    .filter((part) => part.type === 'citations')
    .flatMap((part) => Array.isArray(part.items) ? part.items : [])
    .map(record);
  const analysis = record(message.response_payload.analysis);
  const primary = record(analysis.primary);
  const knowledge = record(primary.knowledge ?? primary);
  const legacy = Array.isArray(knowledge.citations) ? knowledge.citations.map(record) : [];
  const source = fromParts.length > 0 ? fromParts : legacy;
  const citations = new Map<string, PublicCitation>();
  source.forEach((item, index) => {
    const resourceId = String(item.resource_id ?? item.document_id ?? item.attachment_id ?? item.citation_id ?? item.id ?? '');
    const title = String(item.title ?? '业务资料');
    const version = String(item.version ?? item.document_version_id ?? '—');
    const locator = String(item.locator ?? item.chunk_id ?? '未提供定位');
    const stableKey = `${resourceId || title}\u0000${version}\u0000${locator}`;
    const renderId = `${resourceId || `${message.id}-${index}`}::${version}::${locator}`;
    if (!citations.has(stableKey)) citations.set(stableKey, { id: renderId, title, version, locator });
  });
  return [...citations.values()];
}

function evidenceData(message: ChatMessage, result: QueryResponse | null, parts = messageParts(message)): EvidenceDrawerData {
  const evidencePart = record(parts.find((part) => part.type === 'evidence'));
  const semantic = record(evidencePart.semantic);
  const guard = record(evidencePart.guard);
  const oracle = record(evidencePart.oracle);
  const phaseValues = Array.isArray(evidencePart.phases) ? evidencePart.phases : [];
  const phaseLabels = phaseValues
    .map((phase) => typeof phase === 'string' ? PUBLIC_PHASES[phase] ?? '' : PUBLIC_PHASES[String(record(phase).phase ?? '')] ?? '')
    .filter(Boolean);
  const defaultPhases = result
    ? ['已理解业务问题', '已识别指标和维度', '已执行只读查询', '已校验结果', '已整理业务回答']
    : message.route === 'KNOWLEDGE_QUERY'
      ? ['已理解业务问题', '已检索授权业务规则', '已核验引用', '已整理业务回答']
      : ['已理解业务问题', '已获取所需证据', '已校验结果', '已整理业务回答'];
  const filters = result?.plan.filters ?? [];
  const resultContext = result?.context ?? {};
  return {
    dataAndSemantics: result ? [
      { label: '数据源', value: String(resultContext.datasource_name ?? result.datasource_id ?? '—') },
      { label: '语义模型', value: `${String(resultContext.semantic_model_name ?? result.semantic_model_id ?? '—')} · v${result.semantic_model_version}` },
      { label: '指标', value: result.plan.metrics?.join('、') || '明细查询' },
      { label: '维度', value: result.plan.dimensions?.join('、') || '无分组' },
      { label: '时间', value: result.plan.time_range?.kind ?? '全部时间' },
      { label: '过滤', value: filters.map((item) => `${item.field} ${item.operator} ${String(item.value)}`).join('、') || '无过滤' },
      { label: '返回数据', value: `${result.execution.row_count ?? 0} 行${result.execution.truncated ? '（已达上限）' : ''}` },
    ] : [
      { label: '回答类型', value: message.route === 'KNOWLEDGE_QUERY' ? '业务知识问答' : message.route === 'FILE_QUERY' ? '附件分析' : '综合业务分析' },
      { label: '证据范围', value: citationsFromMessage(message, parts).length ? '当前工作空间内授权资料' : '当前会话上下文' },
    ],
    sql: String(evidencePart.sql ?? result?.guard.normalized_sql ?? result?.plan.generated_sql ?? '') || undefined,
    businessEvidence: citationsFromMessage(message, parts),
    phases: phaseLabels.length ? phaseLabels : defaultPhases,
    verification: [
      guard.allowed === true || result?.guard.allowed ? '只读查询安全校验通过' : '',
      String(oracle.status ?? result?.oracle.status ?? '') === 'PASSED' ? '指标、维度、过滤与结果值已校验' : '',
      semantic.model_version || result?.semantic_model_version ? '语义口径版本已绑定' : '',
    ].filter(Boolean),
  };
}

function ResultStateNotice({ semantic, message, onRetry, testId }: { semantic: ResultSemantic; message?: string; onRetry: () => void; testId?: string }) {
  if (semantic === 'VALUE') return null;
  if (semantic === 'ZERO') return <section className="result-state-notice zero"><strong>当前条件下结果为 0</strong><p>查询命中了记录，指标值经过校验后确认为数值 0。</p></section>;
  if (semantic === 'NO_ROWS') return <section className="result-state-notice no-rows" data-testid="query-empty"><strong>没有匹配记录</strong><p>当前条件下查询成功但没有返回记录，这并不代表指标为 0。可调整时间或筛选条件后重试。</p></section>;
  if (semantic === 'NULL_VALUE') return <section className="result-state-notice null-value"><strong>查询到记录，但指标字段为空</strong><p>空值不会转换为 0，也不会据此生成趋势或因果结论。</p></section>;
  return <section className="result-state-notice failed" data-testid={testId}><h2>回答未完成</h2><p>{message || '查询、权限、模型、数据源或结果校验失败。'}</p><button type="button" onClick={onRetry}>重新查询</button></section>;
}

function AnswerActions({ message, result, onRetry, onEvidence, evidenceButtonRef }: { message: ChatMessage; result: QueryResponse | null; onRetry: () => void; onEvidence: () => void; evidenceButtonRef: RefObject<HTMLButtonElement> }) {
  const [copyStatus, setCopyStatus] = useState('');
  const [feedback, setFeedback] = useState('');
  const [saved, setSaved] = useState(false);

  async function copyAnswer() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopyStatus('已复制');
    } catch {
      setCopyStatus('复制失败');
    }
  }

  async function recordFeedback(type: 'HELPFUL' | 'NOT_HELPFUL') {
    if (!result) return;
    await queryApi.feedback(result.id, type);
    setFeedback(type === 'HELPFUL' ? '已记录“有帮助”' : '已记录改进反馈');
  }

  async function saveAnswer() {
    if (!result) return;
    await queryApi.save(result.id);
    setSaved(true);
  }

  return (
    <footer className="answer-actions">
      <button type="button" onClick={() => void copyAnswer()} aria-label="复制回答">复制</button>
      <button type="button" onClick={onRetry}>重新生成</button>
      <button ref={evidenceButtonRef} type="button" onClick={onEvidence}>查看 SQL 与执行明细</button>
      {result && <button type="button" onClick={() => void recordFeedback('HELPFUL')}>结果有帮助</button>}
      {result && <button type="button" onClick={() => void recordFeedback('NOT_HELPFUL')}>需要改进</button>}
      {result && <button type="button" disabled={feedback !== '已记录“有帮助”' || saved} onClick={() => void saveAnswer()}>{saved ? '已保存到答案库' : '保存为已验证答案'}</button>}
      {(copyStatus || feedback) && <span role="status">{copyStatus || feedback}</span>}
    </footer>
  );
}

function QueryAnswer({ message, result, onAsk, onRetry }: { message: ChatMessage; result: QueryResponse; onAsk: (question: string) => void; onRetry: () => void }) {
  const semantic = inferSemantic(message, result);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const evidenceButtonRef = useRef<HTMLButtonElement>(null);
  const rows = result.execution.rows ?? [];
  const columns = result.execution.columns ?? [];
  const chartSpec = 'chart_type' in result.chart_spec ? result.chart_spec as ChartSpec : null;
  const narrative = 'conclusion' in result.narrative ? result.narrative as Narrative : null;
  const kpis = result.kpis.length ? result.kpis : narrative?.key_metrics ?? [];
  const citations = citationsFromMessage(message);
  const conclusion = semantic === 'ZERO' ? '当前条件下结果为 0。' : narrative?.conclusion || message.content || result.summary;
  const stateError = result.status === 'SECURITY_REJECTED'
    ? `${result.error_code ?? 'SQL_GUARD_REJECTED'}：${result.error_message ?? '查询已被安全策略拒绝，未访问数据库。'}`
    : result.status === 'ORACLE_MISMATCH'
      ? `结果未通过一致性校验（${result.oracle.mismatch_count ?? 0} 项差异），不会作为已验证答案发布。`
      : `${result.error_code ?? message.error_code ?? 'QUERY_FAILED'}：${result.error_message ?? '请稍后重试。'}`;
  const success = semantic !== 'FAILED';

  return (
    <article className="assistant-response" data-testid={`result-state-${semantic}`}>
      <header className="assistant-response-head"><span aria-hidden="true">BI</span><strong>ChatBI</strong>{success && result.guard.allowed && result.oracle.status === 'PASSED' && <small>查询执行已校验</small>}</header>
      {success && semantic !== 'NO_ROWS' && semantic !== 'NULL_VALUE' && <section className="answer-conclusion"><h2 className="sr-only">分析结论</h2><h2>核心结论</h2><p>{conclusion}</p></section>}
      <ResultStateNotice semantic={semantic} message={stateError} onRetry={onRetry} testId={result.status === 'SECURITY_REJECTED' ? 'query-security' : result.status === 'ORACLE_MISMATCH' ? 'query-mismatch' : undefined} />

      {(semantic === 'VALUE' || semantic === 'ZERO') && (
        <div data-testid="query-success">
          {kpis.length > 0 && <section className="answer-card kpi-card"><h3>KPI</h3><div className="answer-kpi-grid">{kpis.slice(0, 4).map((kpi) => <article key={kpi.label}><span>{kpi.label}</span><strong>{formatValue(kpi.value)}{kpi.unit ?? ''}</strong><small>已验证指标</small></article>)}</div></section>}
          {chartSpec && <section className="answer-card chart-card"><header><h3>{chartSpec.title}</h3><small>绑定本次查询结果</small></header><EChartsRenderer spec={chartSpec} execution={result.execution} label="真实查询结果图表" />{chartSpec.warnings.map((warning) => <p className="chart-warning" key={warning}>{warning}</p>)}</section>}
          {narrative?.insights.length ? <section className="answer-insights"><h3>业务洞察</h3>{narrative.insights.map((insight) => <p key={insight}>{insight}</p>)}</section> : null}
          {columns.length > 0 && rows.length > 0 && <section className="answer-card table-card"><header><h3>明细数据</h3><small>{result.execution.row_count ?? rows.length} 行</small></header><div className="answer-table-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 20).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div></section>}
          {citations.length > 0 && <section className="answer-card citations-card" data-testid="citation-evidence"><h3>业务依据</h3>{citations.map((citation) => <article key={citation.id}><strong>{citation.title}</strong><small>版本 {citation.version} · {citation.locator}</small></article>)}</section>}
          {result.recommended_questions.length > 0 && <section className="answer-followups"><h3>推荐追问</h3><div>{result.recommended_questions.slice(0, 5).map((question) => <button type="button" key={question} onClick={() => onAsk(question)}>{question}</button>)}</div></section>}
        </div>
      )}
      {semantic === 'NULL_VALUE' && columns.length > 0 && rows.length > 0 && <section className="answer-card table-card"><header><h3>明细数据</h3><small>{result.execution.row_count ?? rows.length} 行</small></header><div className="answer-table-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 20).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div></section>}

      <AnswerActions message={message} result={success ? result : null} onRetry={onRetry} onEvidence={() => setDrawerOpen(true)} evidenceButtonRef={evidenceButtonRef} />
      {drawerOpen && <EvidenceDrawer data={evidenceData(message, result)} onClose={() => setDrawerOpen(false)} returnFocusRef={evidenceButtonRef} />}
    </article>
  );
}

function safeArtifactUrl(value: unknown) {
  const url = String(value ?? '');
  return url.startsWith('/api/') ? url : '';
}

function GeneralAnswer({ message, onAsk, onRetry }: { message: ChatMessage; onAsk: (question: string) => void; onRetry: () => void }) {
  const semantic = inferSemantic(message, null);
  const artifactSuccess = semantic === 'VALUE' || semantic === 'ZERO';
  const parts = messageParts(message);
  const citations = citationsFromMessage(message, parts);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const evidenceButtonRef = useRef<HTMLButtonElement>(null);
  const kpis = parts.filter((part) => part.type === 'kpi').flatMap((part) => Array.isArray(part.items) ? part.items.map(record) : []);
  const insightTexts = parts.filter((part) => part.type === 'text' && part.role === 'insights').map((part) => String(part.text ?? '')).filter(Boolean);
  const followups = parts
    .filter((part) => part.type === 'text' && part.role === 'followups')
    .flatMap((part) => String(part.text ?? '').split('\n').map((item) => item.trim()).filter(Boolean));
  const table = record(parts.find((part) => part.type === 'table'));
  const tableColumns = Array.isArray(table.columns) ? table.columns.map(String) : [];
  const tableRows = Array.isArray(table.rows) ? table.rows.map(record) : [];
  const chartPart = record(parts.find((part) => part.type === 'chart'));
  const structuredChartSpec = record(chartPart.chart_spec);
  const hasStructuredChart = typeof structuredChartSpec.chart_type === 'string'
    && typeof structuredChartSpec.version === 'string'
    && Array.isArray(structuredChartSpec.series)
    && Array.isArray(structuredChartSpec.y_fields)
    && tableColumns.length > 0
    && tableRows.length > 0;
  const fileAnalysis = record(record(message.response_payload).file_analysis);
  const fileResult = record(fileAnalysis.result);
  const fallbackColumns = Array.isArray(fileResult.columns) ? fileResult.columns.map(String) : [];
  const fallbackRows = Array.isArray(fileResult.rows) ? fileResult.rows.map(record) : [];
  const fileChart = record(fileAnalysis.chart);
  const chartDefinition = Object.keys(fileChart).length ? fileChart : structuredChartSpec;
  const chartRows = Array.isArray(chartDefinition.rows) ? chartDefinition.rows.map(record) : tableRows;
  const xField = typeof chartDefinition.x === 'string' ? chartDefinition.x : typeof chartDefinition.x_field === 'string' ? chartDefinition.x_field : '';
  const yFields = Array.isArray(chartDefinition.y_fields) ? chartDefinition.y_fields.map(String) : [];
  const yField = typeof chartDefinition.y === 'string' ? chartDefinition.y : yFields[0] ?? '';
  const chartOption = xField && yField ? {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: chartRows.map((row) => formatValue(row[xField])) },
    yAxis: { type: 'value' },
    series: [{ type: chartDefinition.chart_type === 'line' || chartDefinition.chart_type === 'LINE' ? 'line' : 'bar', data: chartRows.map((row) => Number(row[yField]) || 0) }],
  } : null;
  const artifacts = Array.isArray(fileAnalysis.artifacts) ? fileAnalysis.artifacts.map(record) : [];
  const displayColumns = tableColumns.length ? tableColumns : fallbackColumns;
  const displayRows = tableRows.length ? tableRows : fallbackRows;
  const displayRowCount = Number(table.row_count ?? fileResult.row_count ?? displayRows.length);

  return (
    <article className="assistant-response" data-testid={`result-state-${semantic}`}>
      <header className="assistant-response-head"><span aria-hidden="true">BI</span><strong>ChatBI</strong>{artifactSuccess && <small>回答已完成</small>}</header>
      {artifactSuccess && <section className="answer-conclusion"><h2>核心结论</h2><p>{message.content}</p></section>}
      <ResultStateNotice semantic={semantic} message={message.error_code ? `${message.error_code}：${message.content}` : message.content} onRetry={onRetry} />
      {artifactSuccess && kpis.length > 0 && <section className="answer-card kpi-card"><h3>KPI</h3><div className="answer-kpi-grid">{kpis.slice(0, 4).map((kpi, index) => <article key={String(kpi.label ?? index)}><span>{String(kpi.label ?? '指标')}</span><strong>{formatValue(kpi.value)}{String(kpi.unit ?? '')}</strong></article>)}</div></section>}
      {artifactSuccess && hasStructuredChart && <section className="answer-card chart-card"><header><h3>{String(structuredChartSpec.title ?? '分析图表')}</h3><small>绑定本次查询结果</small></header><EChartsRenderer spec={structuredChartSpec as unknown as ChartSpec} execution={{ columns: tableColumns, rows: tableRows, row_count: displayRowCount, result_signature: String(chartPart.result_signature ?? '') }} label="真实查询结果图表" /></section>}
      {artifactSuccess && !hasStructuredChart && chartOption && <section className="answer-card chart-card"><h3>分析图表</h3><EChart option={chartOption} label="文件分析结果图表" className="file-analysis-chart" /></section>}
      {artifactSuccess && insightTexts.length > 0 && <section className="answer-insights"><h3>业务洞察</h3>{insightTexts.map((insight) => <p key={insight}>{insight}</p>)}</section>}
      {(artifactSuccess || semantic === 'NULL_VALUE') && displayColumns.length > 0 && displayRows.length > 0 && <section className="answer-card table-card" data-testid="file-analysis-evidence"><header><h3>明细数据</h3><small>{displayRowCount} 行</small></header><div className="answer-table-scroll"><table><thead><tr>{displayColumns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{displayRows.slice(0, 20).map((row, index) => <tr key={index}>{displayColumns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div>{artifacts.length > 0 && <footer className="artifact-links">{artifacts.flatMap((artifact, index) => {
        const csv = safeArtifactUrl(artifact.csv_url);
        const json = safeArtifactUrl(artifact.json_url);
        return [csv && <a key={`csv-${index}`} href={csv}>下载 CSV Artifact</a>, json && <a key={`json-${index}`} href={json}>下载 JSON Artifact</a>].filter(Boolean);
      })}</footer>}</section>}
      {semantic !== 'FAILED' && semantic !== 'NO_ROWS' && citations.length > 0 && <section className="answer-card citations-card" data-testid="citation-evidence"><h3>业务依据</h3>{citations.map((citation) => <article key={citation.id}><strong>{citation.title}</strong><small>版本 {citation.version} · {citation.locator}</small></article>)}</section>}
      {artifactSuccess && followups.length > 0 && <section className="answer-followups"><h3>推荐追问</h3><div>{followups.slice(0, 5).map((question) => <button type="button" key={question} onClick={() => onAsk(question)}>{question}</button>)}</div></section>}
      <AnswerActions message={message} result={null} onRetry={onRetry} onEvidence={() => setDrawerOpen(true)} evidenceButtonRef={evidenceButtonRef} />
      {drawerOpen && <EvidenceDrawer data={evidenceData(message, null, parts)} onClose={() => setDrawerOpen(false)} returnFocusRef={evidenceButtonRef} />}
    </article>
  );
}

function AssistantMessage({ message, onAsk, onRetry }: { message: ChatMessage; onAsk: (question: string) => void; onRetry: () => void }) {
  const result = queryFromMessage(message);
  return result ? <QueryAnswer message={message} result={result} onAsk={onAsk} onRetry={onRetry} /> : <GeneralAnswer message={message} onAsk={onAsk} onRetry={onRetry} />;
}

function PendingAssistant({ turn, onRetry }: { turn: PendingTurn; onRetry: () => void }) {
  if (turn.status === 'FAILED') return <article className="assistant-response pending" data-testid="result-state-FAILED"><header className="assistant-response-head"><span aria-hidden="true">BI</span><strong>ChatBI</strong></header><ResultStateNotice semantic="FAILED" message={turn.error} onRetry={onRetry} /></article>;
  return (
    <article className="assistant-response pending" aria-busy={turn.status !== 'CANCELLED'}>
      <header className="assistant-response-head"><span aria-hidden="true">BI</span><strong>ChatBI</strong></header>
      {turn.content && <section className="pending-answer-text"><p>{turn.content}</p><span className="stream-caret" aria-hidden="true" /></section>}
      {turn.status === 'CANCELLED' ? <p className="cancelled-run">已停止生成，不会继续追加内容。</p> : <p className="public-stage" role="status" aria-live="polite"><span aria-hidden="true" />{turn.stage || '正在开始分析……'}</p>}
    </article>
  );
}

function mergeResponseMessages(current: ChatMessage[], response: ChatResponse) {
  const ids = new Set([response.user_message.id, response.assistant_message.id]);
  return [...current.filter((message) => !ids.has(message.id)), response.user_message, response.assistant_message];
}

export function AskPage({ results = false }: { results?: boolean }) {
  const location = useLocation();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState<UploadState[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [pendingTurn, setPendingTurn] = useState<PendingTurn | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [pageError, setPageError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const activeRunRef = useRef<{ id: string; conversationId: string; cancelled: boolean } | null>(null);
  const interactionRef = useRef<{ generation: number; submissionId: string | null }>({ generation: 0, submissionId: null });
  const creationPromiseRef = useRef<{ generation: number; promise: Promise<ConversationDetail> } | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const messageAreaRef = useRef<HTMLDivElement | null>(null);
  const compositionRef = useRef(false);
  const initialQuestionRef = useRef('');

  function cancelActiveRunForNavigation() {
    interactionRef.current.generation += 1;
    interactionRef.current.submissionId = null;
    const run = activeRunRef.current;
    setSending(false);
    if (!run) return interactionRef.current.generation;
    run.cancelled = true;
    activeRunRef.current = null;
    const controller = abortRef.current;
    abortRef.current = null;
    setPendingTurn((current) => current?.runId === run.id ? null : current);
    controller?.abort();
    return interactionRef.current.generation;
  }

  async function openConversation(id: string) {
    const generation = id !== detail?.id ? cancelActiveRunForNavigation() : interactionRef.current.generation;
    const [value, files] = await Promise.all([chatApi.conversation(id), chatApi.attachments(id)]);
    if (interactionRef.current.generation !== generation) return;
    localStorage.setItem('chatbi_conversation_id', id);
    setDetail(value);
    setAttachments(files);
    setPageError('');
    setIsAtBottom(true);
  }

  async function refreshConversations() {
    const items = await chatApi.conversations();
    setConversations(items);
    return items;
  }

  function startLocalConversation() {
    cancelActiveRunForNavigation();
    localStorage.removeItem('chatbi_conversation_id');
    setDetail(null);
    setAttachments([]);
    setUploading([]);
    setDraft('');
    setPageError('');
    setPendingTurn((current) => current?.status === 'FAILED' || current?.status === 'CANCELLED' ? null : current);
    setIsAtBottom(true);
  }

  async function ensureConversation() {
    if (detail) return detail;
    const generation = interactionRef.current.generation;
    if (creationPromiseRef.current?.generation === generation) return creationPromiseRef.current.promise;
    const promise = chatApi.createConversation()
      .then((item) => ({ ...item, messages: [] } as ConversationDetail))
      .finally(() => {
        if (creationPromiseRef.current?.promise === promise) creationPromiseRef.current = null;
      });
    creationPromiseRef.current = { generation, promise };
    return promise;
  }

  function adoptCreatedConversation(target: ConversationDetail, generation: number) {
    if (interactionRef.current.generation !== generation) return false;
    setConversations((items) => [target, ...items.filter((value) => value.id !== target.id)]);
    setDetail((current) => current ?? target);
    localStorage.setItem('chatbi_conversation_id', target.id);
    return true;
  }

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const items = await refreshConversations();
        if (!active) return;
        const params = new URLSearchParams(location.search);
        const requested = params.get('conversation_id');
        const localNew = params.get('new') === '1' || Boolean(params.get('q')?.trim() && !params.get('query_id'));
        if (localNew) {
          startLocalConversation();
          return;
        }
        const visibleItems = items.filter(isVisibleConversation);
        const remembered = localStorage.getItem('chatbi_conversation_id');
        const id = [requested, remembered, visibleItems[0]?.id].find((candidate) => candidate && visibleItems.some((item) => item.id === candidate));
        if (id) await openConversation(id);
        else startLocalConversation();
      } catch (reason) {
        if (active) setPageError(reason instanceof Error ? reason.message : '会话加载失败');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      interactionRef.current.generation += 1;
      interactionRef.current.submissionId = null;
      if (activeRunRef.current) activeRunRef.current.cancelled = true;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const messageArea = messageAreaRef.current;
    if (!isAtBottom || !messageArea) return;
    if (typeof messageArea.scrollTo === 'function') messageArea.scrollTo({ top: messageArea.scrollHeight, behavior: 'smooth' });
    else messageArea.scrollTop = messageArea.scrollHeight;
  }, [detail?.messages.length, pendingTurn?.content, pendingTurn?.stage, isAtBottom]);

  async function sendMessage(value = draft) {
    const question = value.trim();
    if (sending || interactionRef.current.submissionId || (!question && attachments.length === 0)) return;
    const submissionId = crypto.randomUUID();
    const submissionGeneration = interactionRef.current.generation;
    interactionRef.current.submissionId = submissionId;
    const isCurrentSubmission = () => interactionRef.current.generation === submissionGeneration && interactionRef.current.submissionId === submissionId;

    try {
      let target: ConversationDetail;
      try {
        target = await ensureConversation();
      } catch (reason) {
        if (isCurrentSubmission()) setPageError(reason instanceof Error ? reason.message : '创建会话失败');
        return;
      }
      if (!isCurrentSubmission()) return;
      if (!adoptCreatedConversation(target, submissionGeneration)) return;

      const clientMessageId = submissionId;
      const parent = [...target.messages].reverse().find((item) => item.role === 'assistant')?.id;
      const readyAttachmentIds = attachments.filter((item) => item.status === 'READY' && item.conversation_id === target.id).map((item) => item.id);
      const optimisticUser: ChatMessage = {
        id: `pending-${clientMessageId}`,
        conversation_id: target.id,
        parent_message_id: parent,
        role: 'user',
        content: question || '请分析当前附件。',
        status: 'SENDING',
        attachment_ids: readyAttachmentIds,
        response_payload: {},
        trace_payload: {},
        created_at: new Date().toISOString(),
      };
      const controller = new AbortController();
      abortRef.current = controller;
      activeRunRef.current = { id: clientMessageId, conversationId: target.id, cancelled: false };
      setSending(true);
      setPageError('');
      setLastQuestion(question || optimisticUser.content);
      setDraft('');
      setIsAtBottom(true);
      setPendingTurn({ runId: clientMessageId, conversationId: target.id, user: optimisticUser, content: '', parts: [], stage: PUBLIC_PHASES.understanding, status: 'SUBMITTING' });

      const isCurrentRun = () => isCurrentSubmission() && activeRunRef.current?.id === clientMessageId && !activeRunRef.current.cancelled;
      const handlers: StreamHandlers = {
        onStateChange: (state) => {
          if (!isCurrentRun()) return;
          const normalized = state.toUpperCase() as RunStatus;
          setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, status: normalized } : current);
        },
        onDelta: (delta) => {
          if (!delta || !isCurrentRun()) return;
          setPendingTurn((current) => current?.runId === clientMessageId && current.status !== 'CANCELLED' ? { ...current, content: `${current.content}${delta}`, status: 'STREAMING' } : current);
        },
        onEvent: (event) => {
          if (!isCurrentRun()) return;
          if (event.event_type === 'phase.started' || event.event_type === 'phase.completed') {
            const label = PUBLIC_PHASES[String(event.phase ?? '')];
            if (label) setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, stage: label, status: 'RUNNING' } : current);
          } else if (event.event_type === 'artifact.ready' && event.artifact_type && event.artifact) {
            setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, parts: [...current.parts, { type: event.artifact_type!, ...event.artifact }] } : current);
          } else if (event.event_type === 'citations.ready' && Array.isArray(event.citations)) {
            setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, parts: [...current.parts, { type: 'citations', items: event.citations }] } : current);
          } else if (event.event_type === 'run.failed') {
            setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, status: 'FAILED', semantic: 'FAILED', error: event.message ?? event.code ?? '回答失败' } : current);
          } else if (event.event_type === 'run.cancelled') {
            if (activeRunRef.current) activeRunRef.current.cancelled = true;
            setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, status: 'CANCELLED' } : current);
          } else if (event.event_type === 'run.completed') {
            setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, status: 'COMPLETED', semantic: event.result_semantic, parts: event.message_parts ?? current.parts } : current);
          }
        },
      };

      try {
        const response = await streamingApi.stream({
          conversation_id: target.id,
          content: question,
          parent_message_id: parent,
          client_message_id: clientMessageId,
          attachment_ids: readyAttachmentIds,
        }, handlers, controller.signal);
        if (!isCurrentRun()) return;
        setDetail((current) => current?.id === target.id ? { ...response.conversation, messages: mergeResponseMessages(current.messages, response) } : current);
        setConversations((items) => [response.conversation, ...items.filter((item) => item.id !== response.conversation.id)]);
        setPendingTurn((current) => current?.runId === clientMessageId ? null : current);
      } catch (reason) {
        if (!isCurrentSubmission()) return;
        const aborted = controller.signal.aborted || (reason as Error).name === 'AbortError';
        if (aborted) {
          setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, status: 'CANCELLED', stage: '' } : current);
        } else {
          setPendingTurn((current) => current?.runId === clientMessageId ? { ...current, status: 'FAILED', semantic: 'FAILED', error: reason instanceof Error ? reason.message : '回答失败' } : current);
        }
      } finally {
        if (activeRunRef.current?.id === clientMessageId) {
          setSending(false);
          abortRef.current = null;
          if (activeRunRef.current) activeRunRef.current.cancelled = activeRunRef.current.cancelled || controller.signal.aborted;
        }
      }
    } finally {
      if (interactionRef.current.submissionId === submissionId) interactionRef.current.submissionId = null;
    }
  }

  useEffect(() => {
    const initial = new URLSearchParams(location.search).get('q')?.trim();
    if (!results || !initial || loading || sending || initialQuestionRef.current === initial) return;
    if (detail?.messages.some((item) => item.role === 'user' && item.content === initial)) {
      initialQuestionRef.current = initial;
      return;
    }
    initialQuestionRef.current = initial;
    void sendMessage(initial);
  }, [loading, results, location.search, detail?.id]);

  async function uploadFiles(files: File[]) {
    const selected = files.slice(0, 8);
    if (!selected.length) return;
    const uploadGeneration = interactionRef.current.generation;
    const isCurrentUpload = () => interactionRef.current.generation === uploadGeneration;
    const entries = selected.map((file, index) => ({ id: `${Date.now()}-${index}-${file.name}`, name: file.name, progress: 0, file }));
    setUploading((items) => [...items, ...entries]);
    let target: ConversationDetail;
    try {
      target = await ensureConversation();
    } catch (reason) {
      if (!isCurrentUpload()) return;
      const message = reason instanceof Error ? reason.message : '创建会话失败';
      setUploading((items) => items.map((item) => entries.some((entry) => entry.id === item.id) ? { ...item, error: message } : item));
      return;
    }
    if (!isCurrentUpload() || !adoptCreatedConversation(target, uploadGeneration)) return;
    for (const entry of entries) {
      if (!isCurrentUpload()) return;
      try {
        const item = await chatApi.upload(target.id, entry.file, (progress) => {
          if (isCurrentUpload()) setUploading((items) => items.map((value) => value.id === entry.id ? { ...value, progress } : value));
        });
        if (!isCurrentUpload()) return;
        setAttachments((items) => [...items.filter((value) => value.id !== item.id), item]);
        setUploading((items) => items.filter((value) => value.id !== entry.id));
      } catch (reason) {
        if (isCurrentUpload()) setUploading((items) => items.map((value) => value.id === entry.id ? { ...value, error: reason instanceof Error ? reason.message : '上传失败' } : value));
      }
    }
  }

  function retryUpload(item: UploadState) {
    setUploading((items) => items.filter((value) => value.id !== item.id));
    void uploadFiles([item.file]);
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const images = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'));
    if (images.length) {
      event.preventDefault();
      void uploadFiles(images);
    }
  }

  function onDrop(event: DragEvent<HTMLFormElement>) {
    event.preventDefault();
    void uploadFiles(Array.from(event.dataTransfer.files));
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !compositionRef.current && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void sendMessage();
    }
  }

  async function removeAttachment(item: Attachment) {
    await chatApi.deleteAttachment(item.id);
    setAttachments((items) => items.filter((value) => value.id !== item.id));
  }

  async function renameConversation(id: string, title: string) {
    const item = await streamingApi.renameConversation(id, title);
    setConversations((items) => items.map((value) => value.id === id ? item : value));
    setDetail((current) => current?.id === id ? { ...current, ...item } : current);
  }

  async function deleteConversation(id: string) {
    if (detail?.id === id || activeRunRef.current?.conversationId === id) cancelActiveRunForNavigation();
    await chatApi.deleteConversation(id);
    const items = await refreshConversations();
    if (detail?.id !== id) return;
    const next = items.find(isVisibleConversation);
    if (next) await openConversation(next.id);
    else startLocalConversation();
  }

  function stopGeneration() {
    const activeRun = activeRunRef.current;
    const controller = abortRef.current;
    if (activeRun) activeRun.cancelled = true;
    setPendingTurn((current) => current ? { ...current, status: 'CANCELLED', stage: '' } : current);
    if (!activeRun) {
      controller?.abort();
      return;
    }
    void chatApi.cancelStream(activeRun.conversationId, activeRun.id)
      .catch(() => undefined)
      .finally(() => controller?.abort());
  }

  const pendingForCurrent = pendingTurn && pendingTurn.conversationId === detail?.id ? pendingTurn : null;
  const messages = detail?.messages ?? [];
  const isEmpty = messages.length === 0 && !pendingForCurrent;

  if (loading) return <div className="loading">正在恢复会话…</div>;
  return (
    <section className={`chat-workspace${collapsed ? ' conversations-collapsed' : ''}`}>
      <ConversationSidebar
        conversations={conversations}
        activeId={detail?.id}
        collapsed={collapsed}
        localEmpty={!detail}
        generatingConversationId={sending ? activeRunRef.current?.conversationId : undefined}
        onCollapse={() => setCollapsed((value) => !value)}
        onNew={startLocalConversation}
        onOpen={openConversation}
        onRename={renameConversation}
        onDelete={deleteConversation}
      />

      <div className="chat-panel">
        <div className="chat-message-area" ref={messageAreaRef} onScroll={(event) => {
          const node = event.currentTarget;
          setIsAtBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 96);
        }}>
          <div className="chat-message-column">
            {isEmpty && <section className="chat-empty"><div className="hero-mark" aria-hidden="true">BI</div><h1>今天想了解哪些业务数据？</h1><p>直接提问、连续追问，或上传文件与图片开始分析。</p><div className="prompt-grid">{prompts.map(([icon, title, sub]) => <button key={title} type="button" onClick={() => void sendMessage(title)}><b aria-hidden="true">{icon}</b><span><strong>{title}</strong><small>{sub}</small></span></button>)}</div></section>}
            {messages.map((message) => message.role === 'user'
              ? <article className="chat-user-bubble" key={message.id}><p>{message.content}</p>{message.attachment_ids.length > 0 && <small>{message.attachment_ids.length} 个附件</small>}</article>
              : <div className="chat-assistant-message" key={message.id}><AssistantMessage message={message} onAsk={(question) => void sendMessage(question)} onRetry={() => void sendMessage(messages.find((item) => item.id === message.parent_message_id)?.content || lastQuestion)} /></div>)}
            {pendingForCurrent && <><article className="chat-user-bubble pending-user" key={pendingForCurrent.user.id}><p>{pendingForCurrent.user.content}</p>{pendingForCurrent.user.attachment_ids.length > 0 && <small>{pendingForCurrent.user.attachment_ids.length} 个附件</small>}</article><div className="chat-assistant-message"><PendingAssistant turn={pendingForCurrent} onRetry={() => void sendMessage(lastQuestion)} /></div></>}
            {pageError && <section className="page-chat-error" role="alert"><strong>会话暂时不可用</strong><p>{pageError}</p></section>}
          </div>
        </div>

        {!isAtBottom && <button className="back-to-latest" type="button" onClick={() => {
          setIsAtBottom(true);
          const node = messageAreaRef.current;
          if (node && typeof node.scrollTo === 'function') node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' });
        }}>回到最新消息 ↓</button>}

        <div className="chat-composer-zone">
          <form className="chat-composer" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void sendMessage(); }} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
            {(attachments.length > 0 || uploading.length > 0) && <div className="attachment-strip">{attachments.map((item) => <span key={item.id} className={item.status === 'FAILED' ? 'failed' : ''}><b aria-hidden="true">{item.kind === 'IMAGE' ? '图' : item.kind === 'STRUCTURED' ? '表' : '文'}</b><em>{item.filename}</em><small>{item.status === 'PROCESSING' ? '处理中' : item.status === 'FAILED' ? '失败' : '就绪'}</small><button type="button" aria-label={`删除附件 ${item.filename}`} onClick={() => void removeAttachment(item)}>×</button></span>)}{uploading.map((item) => <span key={item.id} className={item.error ? 'failed' : ''}><b aria-hidden="true">传</b><em>{item.name}</em><small>{item.error ?? `${item.progress}%`}</small>{item.error && <button type="button" onClick={() => retryUpload(item)}>重试</button>}</span>)}</div>}
            <textarea
              aria-label="输入业务问题"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              onCompositionStart={() => { compositionRef.current = true; }}
              onCompositionEnd={() => { compositionRef.current = false; }}
              placeholder="输入问题；Enter 发送，Shift+Enter 换行，也可拖拽或粘贴附件"
            />
            <div className="composer-toolbar">
              <input ref={inputRef} hidden multiple type="file" accept=".csv,.xls,.xlsx,.parquet,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp" onChange={(event) => { void uploadFiles(Array.from(event.target.files ?? [])); event.target.value = ''; }} />
              <button type="button" className="attach-button" onClick={() => inputRef.current?.click()} aria-label="添加文件或图片">＋ 文件 / 图片</button>
              <span>附件仅在当前用户、工作空间和会话内可用</span>
              {sending ? <button type="button" className="stop-button" onClick={stopGeneration} aria-label="停止生成"><span aria-hidden="true" />停止生成</button> : <button type="submit" className="ask-submit" aria-label="提交问题" disabled={!draft.trim() && attachments.length === 0}>↑</button>}
            </div>
          </form>
          <p className="composer-footnote">ChatBI 可能出错，请核验关键经营决策。查询始终经过只读与结果校验。</p>
        </div>
      </div>
    </section>
  );
}
