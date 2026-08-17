import { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { chatApi } from '../api/chat';
import { queryApi } from '../api/queries';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import type { Attachment, ChartSpec, ChatMessage, Conversation, ConversationDetail, Narrative, QueryResponse } from '../types/api';
import './ask.css';

const DEFAULT_QUESTION = '2026年按地区按月统计已支付订单收入趋势';
const prompts = [
  ['销', '统计全部订单收入', '收入、订单数、利润等关键指标'],
  ['区', '按地区统计订单收入', '区域对比与经营分布'],
  ['客', '按客户统计订单量前5名', '客户贡献与订单排行'],
  ['品', '按品类统计订单利润前4名', '品类表现与利润结构'],
] as const;

function formatValue(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  return value == null ? '—' : String(value);
}

function AskComposer({ compact = false, initialValue = '', onAsk }: { compact?: boolean; initialValue?: string; onAsk: (question: string) => void }) {
  const [question, setQuestion] = useState(initialValue);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onAsk(question.trim() || DEFAULT_QUESTION);
  }
  if (compact) return (
    <form className="follow-up-composer" onSubmit={submit}>
      <input aria-label="继续追问" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="继续追问，例如：按地区查看订单量……" />
      <button type="submit" aria-label="提交追问">→</button>
    </form>
  );
  return (
    <form className="ask-box" onSubmit={submit}>
      <textarea aria-label="输入业务问题" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：2026年按地区按月统计已支付订单收入趋势" />
      <div className="ask-composer-actions">
        <span className="ask-runtime-note">由语义模型约束 · SQL 只读校验 · 结果独立验证</span>
        <button type="submit" className="ask-submit" aria-label="提交问题">→</button>
      </div>
    </form>
  );
}

function EmptyAskPage({ onAsk }: { onAsk: (question: string) => void }) {
  return (
    <section className="ask-empty">
      <div className="hero-mark" aria-hidden="true">BI</div>
      <h1>今天想了解哪些业务数据？</h1>
      <p>直接用自然语言提问，系统会基于已发布语义模型生成并验证只读查询。</p>
      <AskComposer onAsk={onAsk} />
      <div className="prompt-section">
        <span>猜你想问</span>
        <div className="prompt-grid">
          {prompts.map(([icon, title, sub]) => (
            <button key={title} type="button" onClick={() => onAsk(title)}>
              <b aria-hidden="true">{icon}</b><span><strong>{title}</strong><small>{sub}</small></span>
            </button>
          ))}
        </div>
      </div>
      <footer className="ask-footer">所有结果来自 Backend API 与本机只读数据库连接</footer>
    </section>
  );
}

function QueryState({ kind, title, detail, onRetry }: { kind: string; title: string; detail: string; onRetry?: () => void }) {
  return (
    <section className={`query-state-card ${kind}`} data-testid={`query-${kind}`}>
      <span className="query-state-icon" aria-hidden="true">{kind === 'loading' ? '···' : kind === 'security' ? '盾' : '!'}</span>
      <h1>{title}</h1><p>{detail}</p>
      {onRetry && <button type="button" onClick={onRetry}>重新查询</button>}
    </section>
  );
}

function QueryDetailDialog({ result, onClose }: { result: QueryResponse; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [onClose]);
  const columns = result.execution.columns ?? [];
  const rows = result.execution.rows ?? [];
  return (
    <div className="query-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="query-dialog" role="dialog" aria-modal="true" aria-labelledby="query-detail-title" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>可核验查询依据</span><h2 id="query-detail-title">SQL 与执行明细</h2></div><button type="button" aria-label="关闭查询明细" onClick={onClose}>×</button></header>
        <dl className="query-dialog-meta">
          <div><dt>Query ID</dt><dd>{result.id}</dd></div>
          <div><dt>执行状态</dt><dd>{result.execution.status ?? result.status}</dd></div>
          <div><dt>耗时 / 行数</dt><dd>{result.execution.duration_ms ?? 0} ms / {result.execution.row_count ?? 0} 行</dd></div>
          <div><dt>结果签名</dt><dd className="signature-value">{result.execution.result_signature ?? '—'}</dd></div>
          <div><dt>语义模型</dt><dd>{String(result.context.semantic_model_name ?? result.semantic_model_id)} v{result.semantic_model_version}</dd></div>
          <div><dt>数据源</dt><dd>{String(result.context.datasource_name ?? result.datasource_id)}</dd></div>
          <div><dt>Metric / Dimension</dt><dd>{result.plan.metrics?.join('、') || '明细'} / {result.plan.dimensions?.join('、') || '无分组'}</dd></div>
          <div><dt>Time / Filter / Join</dt><dd>{result.plan.time_range?.kind ?? '全部时间'} / {result.plan.filters?.length ?? 0} / {Array.isArray(result.plan.joins) ? result.plan.joins.length : 0}</dd></div>
          <div><dt>Result Oracle</dt><dd>{result.oracle.status}</dd></div>
        </dl>
        <pre><code>{result.guard.normalized_sql ?? result.plan.generated_sql ?? 'SQL 未生成'}</code></pre>
        <div className="query-detail-table-wrap">
          <table><caption>真实查询明细</caption><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function SuccessfulResult({ result, onAsk }: { result: QueryResponse; onAsk: (question: string) => void }) {
  const [showDetails, setShowDetails] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [saved, setSaved] = useState(false);
  const rows = result.execution.rows ?? [];
  const columns = result.execution.columns ?? [];
  const confidence = Math.round(Number(result.oracle.confidence ?? 0) * 100);
  const metrics = result.plan.metrics ?? [];
  const dimensions = result.plan.dimensions ?? [];
  const filters = result.plan.filters ?? [];
  const checks = result.oracle.checks ?? [];
  const chartSpec = 'chart_type' in result.chart_spec ? result.chart_spec as ChartSpec : null;
  const narrative = 'conclusion' in result.narrative ? result.narrative as Narrative : null;

  async function recordFeedback(type: 'HELPFUL' | 'NOT_HELPFUL') {
    await queryApi.feedback(result.id, type);
    setFeedback(type === 'HELPFUL' ? '已记录“有帮助”' : '已记录改进反馈');
  }
  async function save() {
    await queryApi.save(result.id);
    setSaved(true);
  }
  const runtimeKpis = result.kpis.length ? result.kpis : [
    { label: '返回行数', value: result.execution.row_count ?? 0, unit: ' 行' },
    { label: '查询耗时', value: result.execution.duration_ms ?? 0, unit: ' ms' },
    { label: '只读校验', value: result.guard.allowed ? '通过' : '拒绝', unit: '' },
    { label: '结果校验', value: result.oracle.status ?? 'NOT_RUN', unit: '' },
  ];
  return (
    <section className="ask-results-shell" data-testid="query-success">
      <div className="ask-result-main">
        <div className="analysis-context-bar"><div><span className="context-tag context-tag-brand">真实查询</span><span className="context-tag">{String(result.context.datasource_name ?? '本机数据库')}</span><span className="context-tag">{result.execution.truncated ? '已达行数上限' : `${result.execution.row_count ?? 0} 行`}</span></div><p>语义模型 v{result.semantic_model_version} · {result.provider}</p></div>
        <div className="answer-query">{result.question}</div>
        <article className="analysis-answer-card">
          <header className="analysis-answer-header"><span className="analysis-bi-mark" aria-hidden="true">BI</span><div><h1>分析结论</h1><p>{result.summary} · {result.execution.duration_ms ?? 0} ms</p></div><span className="confidence-badge">可信度 {confidence}%</span></header>
          <div className="analysis-kpi-grid">{runtimeKpis.slice(0, 4).map((kpi) => <section key={kpi.label}><span>{kpi.label}</span><strong>{formatValue(kpi.value)}{kpi.unit}</strong><small>{result.oracle.status === 'PASSED' ? '已通过结果校验' : '需复核'}</small></section>)}</div>
          {chartSpec ? <section className="analysis-chart-card real-chart"><header><h3>{chartSpec.title}</h3><span>{chartSpec.chart_type} · 绑定 Query {chartSpec.data_source_query_id.slice(0, 8)}</span></header><EChartsRenderer spec={chartSpec} execution={result.execution} label="真实查询结果图表" />{chartSpec.warnings.map((warning) => <small key={warning}>{warning}</small>)}</section> : <QueryState kind="empty" title="查询完成，无可绘制图表" detail="明细仍可在下方核验。" />}
          <section className="analysis-insight"><strong>业务洞察：</strong><p>{narrative?.insights.length ? narrative.insights.join('；') : `${checks.filter((check) => check.passed).length}/${checks.length} 项 Oracle 检查通过，当前结果未发现可证明的趋势、贡献或异常。`}</p><small>证据：Query {result.id.slice(0, 8)} · Signature {result.execution.result_signature?.slice(0, 12) ?? '—'} · Semantic v{result.semantic_model_version}</small></section>
          <div className="query-inline-table"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 8).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div>
          <details className="query-evidence-inline"><summary>查询依据</summary><dl><div><dt>Metric</dt><dd>{metrics.join('、') || '明细查询'}</dd></div><div><dt>Dimension</dt><dd>{dimensions.join('、') || '无分组'}</dd></div><div><dt>Time</dt><dd>{result.plan.time_range?.kind ?? '全部时间'}</dd></div><div><dt>Filter</dt><dd>{filters.map((item) => `${item.field}${item.operator}${String(item.value)}`).join('、') || '无过滤'}</dd></div><div><dt>Join</dt><dd>{Array.isArray(result.plan.joins) ? `${result.plan.joins.length} 个` : '0 个'}</dd></div><div><dt>SQL</dt><dd>默认折叠，点击右侧查看</dd></div><div><dt>Semantic Model Version</dt><dd>v{result.semantic_model_version}</dd></div><div><dt>Datasource</dt><dd>{String(result.context.datasource_name ?? result.datasource_id)}</dd></div><div><dt>Execution Time</dt><dd>{result.execution.duration_ms ?? 0} ms</dd></div><div><dt>Result Oracle</dt><dd>{result.oracle.status}</dd></div><div><dt>Result Signature</dt><dd>{result.execution.result_signature ?? '—'}</dd></div></dl></details>
          <section className="followup-suggestions"><h3>推荐追问</h3>{result.recommended_questions.slice(0, 5).map((question) => <button type="button" key={question} onClick={() => onAsk(question)}>{question}</button>)}</section>
        </article>
      </div>
      <aside className="analysis-side-panel" aria-label="查询验证信息">
        <section className="trust-card"><h2>查询可信度</h2><div><span className="trust-ring" style={{ background: `conic-gradient(#5b5cf6 0 ${confidence}%, #eceefe ${confidence}% 100%)` }}><b>{confidence}%</b></span><p><strong>{result.oracle.status === 'PASSED' ? '结果通过校验' : '结果需复核'}</strong><small>指标、维度、过滤、Join 与结果签名</small></p></div></section>
        <section className="evidence-card"><h2>查询依据</h2><dl><div><dt>指标</dt><dd>{metrics.join('、') || '明细查询'}</dd></div><div><dt>维度</dt><dd>{dimensions.join('、') || '无分组'}</dd></div><div><dt>时间 / 过滤</dt><dd>{result.plan.time_range?.kind ?? '全部时间'}；{filters.map((item) => `${item.field}${item.operator}${String(item.value)}`).join('、') || '无过滤'}</dd></div><div><dt>SQL / Oracle</dt><dd>{result.guard.allowed ? '只读校验通过' : '未通过'}；{result.oracle.status}</dd></div></dl><button type="button" className="sql-detail-button" onClick={() => setShowDetails(true)}>查看 SQL 与执行明细</button></section>
        <section className="recommend-card"><h2>反馈与沉淀</h2><div className="feedback-actions"><button type="button" onClick={() => recordFeedback('HELPFUL')}>结果有帮助</button><button type="button" onClick={() => recordFeedback('NOT_HELPFUL')}>需要改进</button></div>{feedback && <p className="action-status">{feedback}</p>}<button type="button" disabled={feedback !== '已记录“有帮助”' || saved} onClick={save}>{saved ? '已保存到答案库' : '保存为已验证答案'}</button></section>
      </aside>
      {showDetails && <QueryDetailDialog result={result} onClose={() => setShowDetails(false)} />}
    </section>
  );
}

function queryFromMessage(message: ChatMessage): QueryResponse | null {
  const analysis = message.response_payload.analysis as { primary?: Record<string, unknown> } | undefined;
  let primary = analysis?.primary;
  if (message.route === 'HYBRID_ANALYSIS' && primary?.data) primary = primary.data as Record<string, unknown>;
  if (primary && typeof primary.id === 'string' && typeof primary.execution === 'object') return primary as unknown as QueryResponse;
  return null;
}

function QueryMessage({ message, onAsk, onRetry }: { message: ChatMessage; onAsk: (question: string) => void; onRetry: () => void }) {
  const result = queryFromMessage(message);
  if (!result) return (
    <article className={`chat-answer-bubble ${message.status === 'FAILED' || message.status === 'REFUSED' ? 'failed' : ''}`}>
      <header><span>BI</span><b>{message.route ?? '回答'}</b><small>{message.status}</small></header>
      <p>{message.content}</p>
      {message.error_code && <code>{message.error_code}</code>}
      {(message.status === 'FAILED' || message.status === 'REFUSED') && <button type="button" onClick={onRetry}>重试</button>}
    </article>
  );
  if (result.status === 'SECURITY_REJECTED') return <QueryState kind="security" title="查询已被安全策略拒绝" detail={`${result.error_code ?? 'SQL_GUARD_REJECTED'}：${result.error_message ?? '未访问数据库'}`} />;
  if (result.status === 'ORACLE_MISMATCH') return <QueryState kind="mismatch" title="结果未通过一致性校验" detail={`${result.oracle.mismatch_count ?? 0} 项差异；该结果不会保存为标准答案。`} />;
  if (result.status === 'FAILED') return <QueryState kind="error" title="查询执行失败" detail={`${result.error_code ?? 'QUERY_FAILED'}：${result.error_message ?? '请稍后重试'}`} onRetry={onRetry} />;
  if ((result.execution.rows ?? []).length === 0) return <QueryState kind="empty" title="查询完成，暂无匹配数据" detail="可调整时间范围或过滤条件后重新提问。" />;
  return <SuccessfulResult result={result} onAsk={onAsk} />;
}

const stageLabels: Record<string, string> = {
  UNDERSTANDING: '正在理解问题', QUERYING_DATA: '正在查询并校验数据', RETRIEVING_KNOWLEDGE: '正在检索授权知识',
  VERIFYING: '正在验证证据', GENERATING_INSIGHT: '正在生成业务结论', COMPLETED: '回答完成',
};

export function AskPage({ results = false }: { results?: boolean }) {
  const location = useLocation();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState<Array<{ name: string; progress: number; error?: string }>>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [stage, setStage] = useState('');
  const [error, setError] = useState('');
  const [lastQuestion, setLastQuestion] = useState('');
  const [isAtBottom, setIsAtBottom] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const messageAreaRef = useRef<HTMLDivElement | null>(null);
  const compositionRef = useRef(false);
  const initialQuestionRef = useRef('');

  async function openConversation(id: string) {
    const [value, files] = await Promise.all([chatApi.conversation(id), chatApi.attachments(id)]);
    localStorage.setItem('chatbi_conversation_id', id);
    setDetail(value); setAttachments(files); setError('');
  }

  async function refreshConversations() {
    const items = await chatApi.conversations(); setConversations(items); return items;
  }

  async function createConversation() {
    const item = await chatApi.createConversation();
    setConversations((values) => [item, ...values]);
    await openConversation(item.id);
  }

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const items = await refreshConversations();
        if (!active) return;
        const params = new URLSearchParams(location.search);
        const requested = params.get('conversation_id');
        const startsNewConversation = params.get('new') === '1' || Boolean(params.get('q')?.trim() && !params.get('query_id'));
        if (startsNewConversation) {
          await createConversation();
          return;
        }
        const remembered = localStorage.getItem('chatbi_conversation_id');
        const id = [requested, remembered, items[0]?.id].find((candidate) => candidate && items.some((item) => item.id === candidate));
        if (id) await openConversation(id); else await createConversation();
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : '会话加载失败'); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; abortRef.current?.abort(); };
  }, []);

  useEffect(() => {
    const messageArea = messageAreaRef.current;
    if (!isAtBottom || !messageArea) return;
    if (typeof messageArea.scrollTo === 'function') {
      messageArea.scrollTo({ top: messageArea.scrollHeight, behavior: 'smooth' });
    } else {
      messageArea.scrollTop = messageArea.scrollHeight;
    }
  }, [detail?.messages.length, sending, isAtBottom]);

  async function sendMessage(value = draft) {
    const question = value.trim();
    if (!detail || sending || (!question && attachments.length === 0)) return;
    const clientMessageId = crypto.randomUUID();
    const parent = [...detail.messages].reverse().find((item) => item.role === 'assistant')?.id;
    const optimisticUser: ChatMessage = {
      id: `pending-${clientMessageId}`,
      conversation_id: detail.id,
      parent_message_id: parent,
      role: 'user',
      content: question || '请分析当前附件。',
      status: 'SENDING',
      attachment_ids: attachments.filter((item) => item.status === 'READY').map((item) => item.id),
      response_payload: {},
      trace_payload: {},
      created_at: new Date().toISOString(),
    };
    setSending(true); setStage('UNDERSTANDING'); setError(''); setLastQuestion(question); setDraft(''); setIsAtBottom(true);
    setDetail((current) => current?.id === detail.id ? { ...current, messages: [...current.messages, optimisticUser] } : current);
    const controller = new AbortController(); abortRef.current = controller;
    try {
      const response = await chatApi.stream({
        conversation_id: detail.id, content: question, parent_message_id: parent, client_message_id: clientMessageId,
        attachment_ids: attachments.filter((item) => item.status === 'READY').map((item) => item.id),
      }, setStage, controller.signal);
      setDetail((current) => current ? {
        ...response.conversation,
        messages: [...current.messages.filter((item) => item.id !== optimisticUser.id), response.user_message, response.assistant_message],
      } : current);
      setConversations((items) => [response.conversation, ...items.filter((item) => item.id !== response.conversation.id)]);
    } catch (reason) {
      if ((reason as Error).name !== 'AbortError') setError(reason instanceof Error ? reason.message : '回答失败');
    } finally { setSending(false); setStage(''); abortRef.current = null; }
  }

  useEffect(() => {
    const initial = new URLSearchParams(location.search).get('q')?.trim();
    if (!results || !initial || !detail || sending || initialQuestionRef.current === initial) return;
    if (detail.messages.some((item) => item.role === 'user' && item.content === initial)) { initialQuestionRef.current = initial; return; }
    initialQuestionRef.current = initial; void sendMessage(initial);
  }, [detail?.id, results]);

  async function uploadFiles(files: File[]) {
    if (!detail) return;
    for (const file of files.slice(0, 8)) {
      setUploading((items) => [...items, { name: file.name, progress: 0 }]);
      try {
        const item = await chatApi.upload(detail.id, file, (progress) => setUploading((items) => items.map((entry) => entry.name === file.name ? { ...entry, progress } : entry)));
        setAttachments((items) => [...items, item]); setUploading((items) => items.filter((entry) => entry.name !== file.name));
      } catch (reason) {
        setUploading((items) => items.map((entry) => entry.name === file.name ? { ...entry, error: reason instanceof Error ? reason.message : '上传失败' } : entry));
      }
    }
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const images = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'));
    if (images.length) { event.preventDefault(); void uploadFiles(images); }
  }

  function onDrop(event: DragEvent<HTMLFormElement>) {
    event.preventDefault(); void uploadFiles(Array.from(event.dataTransfer.files));
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !compositionRef.current && !event.nativeEvent.isComposing) {
      event.preventDefault(); void sendMessage();
    }
  }

  async function removeAttachment(item: Attachment) {
    await chatApi.deleteAttachment(item.id); setAttachments((items) => items.filter((value) => value.id !== item.id));
  }

  async function deleteConversation(id: string) {
    await chatApi.deleteConversation(id); const items = await refreshConversations();
    if (items[0]) await openConversation(items[0].id); else await createConversation();
  }

  if (loading) return <div className="loading">正在恢复会话…</div>;
  return (
    <section className="chat-workspace">
      <aside className="conversation-panel">
        <button type="button" className="new-conversation" onClick={() => void createConversation()}>＋ 新会话</button>
        <div className="conversation-list">{conversations.map((item) => <div key={item.id} data-conversation-id={item.id} className={detail?.id === item.id ? 'active' : ''}><button type="button" onClick={() => void openConversation(item.id)}><strong>{item.title}</strong><small>{item.summary || '暂无消息'}</small></button><button type="button" aria-label={`删除会话 ${item.title}`} onClick={() => void deleteConversation(item.id)}>×</button></div>)}</div>
      </aside>
      <div className="chat-panel">
        <div className="chat-message-area" ref={messageAreaRef} onScroll={(event) => { const node = event.currentTarget; setIsAtBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 80); }}>
          {!detail?.messages.length && <section className="chat-empty"><div className="hero-mark">BI</div><h1>今天想了解哪些业务数据？</h1><p>直接提问、连续追问，或上传文件与图片开始分析。</p><div className="prompt-grid">{prompts.map(([icon, title, sub]) => <button key={title} type="button" onClick={() => void sendMessage(title)}><b>{icon}</b><span><strong>{title}</strong><small>{sub}</small></span></button>)}</div></section>}
          {detail?.messages.map((message) => message.role === 'user'
            ? <article className="chat-user-bubble" key={message.id}><p>{message.content}</p>{message.attachment_ids.length > 0 && <small>{message.attachment_ids.length} 个附件</small>}</article>
            : <div className="chat-assistant-message" key={message.id}><QueryMessage message={message} onAsk={(question) => void sendMessage(question)} onRetry={() => void sendMessage(lastQuestion || detail.messages.find((item) => item.id === message.parent_message_id)?.content || '')} /></div>)}
          {sending && <QueryState kind="loading" title={stageLabels[stage] ?? '正在生成回答'} detail="只公开执行阶段，不展示模型内部推理。" />}
          {error && <QueryState kind="error" title="回答未完成" detail={error} onRetry={lastQuestion ? () => void sendMessage(lastQuestion) : undefined} />}
        </div>
        {!isAtBottom && <button className="back-to-latest" type="button" onClick={() => { setIsAtBottom(true); messageAreaRef.current?.scrollTo({ top: messageAreaRef.current.scrollHeight, behavior: 'smooth' }); }}>回到最新消息</button>}
        <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          {(attachments.length > 0 || uploading.length > 0) && <div className="attachment-strip">{attachments.map((item) => <span key={item.id}><b>{item.kind === 'IMAGE' ? '图' : item.kind === 'STRUCTURED' ? '表' : '文'}</b>{item.filename}<button type="button" aria-label={`删除附件 ${item.filename}`} onClick={() => void removeAttachment(item)}>×</button></span>)}{uploading.map((item) => <span key={item.name} className={item.error ? 'failed' : ''}>{item.name}<small>{item.error ?? `${item.progress}%`}</small>{item.error && <button type="button" onClick={() => inputRef.current?.click()}>重试</button>}</span>)}</div>}
          <textarea aria-label="输入业务问题" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} onPaste={onPaste} onCompositionStart={() => { compositionRef.current = true; }} onCompositionEnd={() => { compositionRef.current = false; }} placeholder="输入问题；Enter 发送，Shift+Enter 换行，也可拖拽或粘贴附件" />
          <div><input ref={inputRef} hidden multiple type="file" accept=".csv,.xls,.xlsx,.parquet,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp" onChange={(event) => { void uploadFiles(Array.from(event.target.files ?? [])); event.target.value = ''; }} /><button type="button" className="attach-button" onClick={() => inputRef.current?.click()}>＋ 文件 / 图片</button><span>附件仅在当前用户、工作空间和会话内可用</span>{sending ? <button type="button" className="stop-button" onClick={() => abortRef.current?.abort()}>停止生成</button> : <button type="submit" className="ask-submit" aria-label="提交问题" disabled={!draft.trim() && attachments.length === 0}>→</button>}</div>
        </form>
      </div>
    </section>
  );
}
