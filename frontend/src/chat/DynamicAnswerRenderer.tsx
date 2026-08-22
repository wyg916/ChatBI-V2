import { useMemo, useState } from 'react';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import { AnswerMarkdown } from '../pages/chat-ui/AnswerMarkdown';
import type { AnswerEnvelope, AnswerTable } from './answerEnvelope';
import { safeArtifactUrl, safeCitationHref } from './answerEnvelope';


function displayValue(value: unknown): string {
  if (typeof value === 'number') return value.toLocaleString('zh-CN', { maximumFractionDigits: 6 });
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return '—';
  }
}


function compareValues(left: unknown, right: unknown): number {
  if (typeof left === 'number' && typeof right === 'number') return left - right;
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return displayValue(left).localeCompare(displayValue(right), 'zh-CN', { numeric: true });
}


function SortableAnswerTable({ table }: { table: AnswerTable }) {
  const pageSize = 10;
  const [sort, setSort] = useState<{ column: string; direction: 'asc' | 'desc' }>();
  const [page, setPage] = useState(0);
  const sortedRows = useMemo(() => {
    if (!sort) return table.rows.map((row, index) => ({ row, index }));
    return table.rows
      .map((row, index) => ({ row, index }))
      .sort((left, right) => {
        const compared = compareValues(left.row[sort.column], right.row[sort.column]);
        return (sort.direction === 'asc' ? compared : -compared) || left.index - right.index;
      });
  }, [sort, table.rows]);
  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleRows = sortedRows.slice(currentPage * pageSize, (currentPage + 1) * pageSize);

  function changeSort(column: string) {
    setSort((current) => current?.column === column
      ? { column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
      : { column, direction: 'asc' });
    setPage(0);
  }

  return (
    <section className="answer-card table-card" data-testid="answer-table">
      <header>
        <h3>明细数据</h3>
        <small>已载入 {table.rows.length} / 共 {table.row_count} 行{table.truncated ? ' · 已截断' : ''}</small>
      </header>
      <div className="answer-table-scroll">
        <table>
          <thead><tr>{table.columns.map((column) => (
            <th key={column} aria-sort={sort?.column === column ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
              <button type="button" onClick={() => changeSort(column)}>{column}{sort?.column === column ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}</button>
            </th>
          ))}</tr></thead>
          <tbody>{visibleRows.map(({ row, index }) => (
            <tr key={`${index}-${table.result_signature ?? 'row'}`}>{table.columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
      {pageCount > 1 && <footer className="answer-table-pagination" aria-label="明细数据分页">
        <button type="button" disabled={currentPage === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>上一页</button>
        <span>第 {currentPage + 1} / {pageCount} 页</span>
        <button type="button" disabled={currentPage + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>下一页</button>
      </footer>}
    </section>
  );
}


export function formatSqlForDisplay(sql: string): string {
  const source = sql.trim().replace(/\s+/g, ' ');
  if (!source) return '';
  return source.replace(
    /\s+(WITH|SELECT|FROM|WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|UNION(?:\s+ALL)?|(?:LEFT|RIGHT|FULL|INNER|CROSS)?\s*JOIN|ON)\s+/gi,
    (_match, keyword: string) => `\n${keyword.toUpperCase().replace(/\s+/g, ' ')} `,
  ).replace(/^\n/, '');
}


function SqlAnswerBlock({ sql }: { sql: string }) {
  const [expanded, setExpanded] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const formatted = useMemo(() => formatSqlForDisplay(sql), [sql]);

  async function copySql() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopyStatus('SQL 已复制');
    } catch {
      setCopyStatus('复制失败');
    }
  }

  return (
    <details className="answer-card answer-sql" data-testid="answer-sql">
      <summary>查看 SQL</summary>
      <div className="answer-sql-actions">
        <button type="button" onClick={() => void copySql()}>复制 SQL</button>
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起' : '展开'}</button>
        {copyStatus && <span role="status">{copyStatus}</span>}
      </div>
      <pre style={{ maxHeight: expanded ? 'none' : '12rem', overflow: 'auto' }}><code>{formatted}</code></pre>
    </details>
  );
}


function CitationList({ envelope }: { envelope: AnswerEnvelope }) {
  if (!envelope.citations.length) return null;
  return (
    <section className="answer-card citations-card" data-testid="answer-citations">
      <h3>业务依据</h3>
      {envelope.citations.map((citation) => {
        const href = safeCitationHref(citation.href);
        return href ? (
          <article key={`${citation.resource_id}:${citation.version}:${citation.locator}`}>
            <a href={href} target={href.startsWith('http') ? '_blank' : undefined} rel={href.startsWith('http') ? 'noopener noreferrer' : undefined}>{citation.title}</a>
            <small>版本 {citation.version} · {citation.locator}</small>
          </article>
        ) : (
          <details key={`${citation.resource_id}:${citation.version}:${citation.locator}`} id={`citation-${citation.id}`}>
            <summary>{citation.title}</summary>
            <small>版本 {citation.version} · 定位 {citation.locator}</small>
          </details>
        );
      })}
    </section>
  );
}


function ArtifactList({ envelope }: { envelope: AnswerEnvelope }) {
  const artifacts = envelope.artifacts.flatMap((artifact) => {
    const url = safeArtifactUrl(artifact.download_url);
    return url ? [{ ...artifact, download_url: url }] : [];
  });
  if (!artifacts.length) return null;
  return (
    <section className="answer-card artifact-card" data-testid="answer-artifacts">
      <h3>可下载产物</h3>
      <div className="artifact-links">{artifacts.map((artifact) => (
        <a
          key={`${artifact.id}:${artifact.download_url}`}
          href={artifact.download_url}
          download
          aria-label={['CSV', 'JSON'].includes(artifact.kind.toUpperCase()) ? `下载 ${artifact.kind.toUpperCase()} Artifact` : undefined}
        >{artifact.name}</a>
      ))}</div>
    </section>
  );
}


function EvidenceBlocks({ envelope }: { envelope: AnswerEnvelope }) {
  return (
    <>
      {envelope.file_evidence.length > 0 && <section className="answer-card file-evidence-card" data-testid="answer-file-evidence">
        <h3>文件证据</h3>
        {envelope.file_evidence.map((item) => <article key={item.attachment_id}>
          <strong>{item.filename}</strong>
          <small>{item.kind}{item.locator ? ` · ${item.locator}` : ''}{item.result_signature ? ' · 结果已签名' : ''}</small>
        </article>)}
      </section>}
      {envelope.visual_evidence.map((item, index) => <section className="answer-card visual-evidence-card" data-testid="answer-visual-evidence" key={item.signature ?? item.attachment_id ?? index}>
        <header><h3>视觉证据</h3><small>{item.injection_detected ? '安全校验未通过' : '安全校验通过'}</small></header>
        {item.sanitized_text && <p>{item.sanitized_text}</p>}
        {item.claims.length > 0 && <dl>{item.claims.map((claim, claimIndex) => <div key={`${claim.claim}:${claimIndex}`}>
          <dt>{claim.claim}</dt><dd>{displayValue(claim.value)}</dd>
          {(claim.dimension || claim.time_range || claim.locator || claim.confidence !== undefined) && <small>{[
            claim.dimension, claim.time_range, claim.locator,
            claim.confidence !== undefined ? `置信度 ${(claim.confidence * 100).toFixed(0)}%` : '',
          ].filter(Boolean).join(' · ')}</small>}
        </div>)}</dl>}
      </section>)}
    </>
  );
}


function AgentSteps({ envelope }: { envelope: AnswerEnvelope }) {
  if (!envelope.agent_steps.length) return null;
  const succeeded = envelope.agent_steps.filter((step) => step.status === 'SUCCEEDED').length;
  return (
    <details className="answer-card agent-steps-card" data-testid="answer-agent-steps">
      <summary>分析协作步骤（{succeeded}/{envelope.agent_steps.length} 完成）</summary>
      <ol>{envelope.agent_steps.map((step) => <li key={`${step.ordinal}:${step.code}:${step.tool_name ?? ''}`}>
        <strong>分析阶段 {step.ordinal}</strong>
        <small>{step.status} · {step.duration_ms} ms{step.error_code ? ` · ${step.error_code}` : ''}</small>
      </li>)}</ol>
    </details>
  );
}


function RuntimeDetails({ envelope }: { envelope: AnswerEnvelope }) {
  const hasRuntime = envelope.provider || envelope.model || envelope.latency.total_ms > 0 || envelope.cost.total_tokens > 0 || envelope.verification.checks.length > 0;
  if (!hasRuntime) return null;
  return (
    <details className="answer-card answer-runtime-details" data-testid="answer-runtime-details">
      <summary>运行与验证信息</summary>
      <dl>
        <div><dt>Trace ID</dt><dd>{envelope.trace_id}</dd></div>
        {envelope.provider && <div><dt>Provider</dt><dd>{envelope.provider}</dd></div>}
        {envelope.model && <div><dt>Model</dt><dd>{envelope.model}</dd></div>}
        <div><dt>总耗时</dt><dd>{envelope.latency.total_ms} ms</dd></div>
        {envelope.cost.total_tokens > 0 && <div><dt>Token</dt><dd>{envelope.cost.total_tokens}{envelope.cost.exact ? '' : '（估算）'}</dd></div>}
        <div><dt>验证状态</dt><dd>{envelope.verification.status}</dd></div>
      </dl>
      {envelope.verification.checks.length > 0 && <ul>{envelope.verification.checks.map((check) => (
        <li key={check.code}>{check.passed === true ? '✓' : check.passed === false ? '✕' : '•'} {check.code}{check.detail ? ` · ${check.detail}` : ''}</li>
      ))}</ul>}
    </details>
  );
}


export interface DynamicAnswerRendererProps {
  envelope: AnswerEnvelope;
  onAsk?: (question: string) => void;
  onRetry?: () => void;
}


export function DynamicAnswerRenderer({ envelope, onAsk, onRetry }: DynamicAnswerRendererProps) {
  const answerText = envelope.markdown || envelope.summary;
  const successful = envelope.status === 'SUCCEEDED' || envelope.status === 'PARTIAL';
  const errorCodes = new Set(envelope.errors.map((error) => error.code));
  const stateTestId = envelope.result_semantic === 'NO_ROWS' || envelope.result_semantic === 'NULL_VALUE'
    ? undefined
    : [...errorCodes].some((code) => code.includes('ORACLE') || code.includes('MISMATCH'))
      ? 'query-mismatch'
      : envelope.result_semantic === 'FAILED'
        ? 'query-security'
        : 'query-success';
  const hasFileArtifact = envelope.artifacts.some((artifact) => ['CSV', 'JSON'].includes(artifact.kind.toUpperCase()));
  const chartLabel = envelope.route === 'FILE_QUERY' || envelope.file_evidence.length > 0 || hasFileArtifact
    ? '文件分析结果图表'
    : envelope.trace_id.startsWith('message-')
      ? '真实查询结果图表'
      : '回答图表';
  return (
    <article className="assistant-response" data-answer-id={envelope.answer_id} data-testid={`result-state-${envelope.result_semantic}`}>
      <header className="assistant-response-head" data-testid={stateTestId}>
        <span aria-hidden="true">BI</span><strong>ChatBI</strong>
        {successful && <small>{envelope.verification.status === 'VERIFIED' ? '查询执行已校验' : '回答已完成'}</small>}
      </header>

      {envelope.result_semantic === 'ZERO' && <section className="result-state-notice zero">
        <strong>当前条件下结果为 0</strong><p>查询命中了记录，指标值经过校验后确认为数值 0。</p>
      </section>}
      {envelope.result_semantic === 'NO_ROWS' && <section className="result-state-notice no-rows" data-testid="query-empty">
        <strong>没有匹配记录</strong><p>当前条件下查询成功但没有返回记录，这并不代表指标为 0。可调整时间或筛选条件后重试。</p>
      </section>}
      {envelope.result_semantic === 'NULL_VALUE' && <section className="result-state-notice null-value">
        <strong>查询到记录，但指标字段为空</strong><p>空值不会转换为 0，也不会据此生成趋势或因果结论。</p>
      </section>}

      {envelope.errors.length > 0 && <section className="result-state-notice failed" role="alert" data-testid="answer-errors">
        <h2>回答未完成</h2>
        {envelope.errors.map((error) => <p key={`${error.code}:${error.message}`}><strong>{error.code}</strong>：{error.message}</p>)}
        {onRetry && envelope.errors.some((error) => error.retryable) && <button type="button" onClick={onRetry}>重新查询</button>}
      </section>}

      {answerText && <section className="answer-conclusion">
        <span className="answer-section-kicker">核心结论</span><h2>分析结论</h2>
        <AnswerMarkdown markdown={answerText} />
      </section>}

      {envelope.kpis.length > 0 && <section className="answer-card kpi-card" data-testid="answer-kpis">
        <h3>KPI</h3><div className="answer-kpi-grid">{envelope.kpis.slice(0, 8).map((kpi) => <article key={kpi.label}><span>{kpi.label}</span><strong>{displayValue(kpi.value)}{kpi.unit}</strong></article>)}</div>
      </section>}

      {envelope.chart && envelope.table && <section className="answer-card chart-card" data-testid="answer-chart">
        <header><h3>{envelope.chart.title}</h3><small>绑定本次结果</small></header>
        <EChartsRenderer spec={envelope.chart} execution={{
          columns: envelope.table.columns,
          rows: envelope.table.rows,
          row_count: envelope.table.row_count,
          result_signature: envelope.table.result_signature,
        }} label={chartLabel} />
      </section>}

      {envelope.insights.length > 0 && <section className="answer-insights" data-testid="answer-insights"><h3>业务洞察</h3>{envelope.insights.map((insight) => <p key={insight}>{insight}</p>)}</section>}

      {envelope.table && (envelope.artifacts.length > 0
        ? <div data-testid="file-analysis-evidence"><SortableAnswerTable table={envelope.table} /></div>
        : <SortableAnswerTable table={envelope.table} />)}
      {envelope.citations.length > 0 && <div data-testid="citation-evidence"><CitationList envelope={envelope} /></div>}
      <EvidenceBlocks envelope={envelope} />
      <ArtifactList envelope={envelope} />

      {envelope.warnings.length > 0 && <section className="answer-card answer-warnings" role="status" data-testid="answer-warnings">
        <h3>注意事项</h3>{envelope.warnings.map((warning) => <p key={`${warning.code}:${warning.message}`}><strong>{warning.code}</strong>：{warning.message}</p>)}
      </section>}

      {envelope.follow_up_suggestions.length > 0 && <section className="answer-followups" data-testid="answer-followups">
        <h3>推荐追问</h3><div>{envelope.follow_up_suggestions.map((question) => <button type="button" key={question} onClick={() => onAsk?.(question)}>{question}</button>)}</div>
      </section>}

      {envelope.sql && <SqlAnswerBlock sql={envelope.sql} />}
      <AgentSteps envelope={envelope} />
      <RuntimeDetails envelope={envelope} />
    </article>
  );
}


export default DynamicAnswerRenderer;
