import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { governanceApi } from '../api/governance';
import type { CostFilters, GovernanceCoverage } from '../api/governance';
import { ErrorNotice, Loading } from '../components/UI';
import './governance.css';

export type GovernanceView = 'cost' | 'trace' | 'model' | 'evaluation';

const views: Array<{ id: GovernanceView; label: string }> = [
  { id: 'cost', label: '成本与用量' },
  { id: 'trace', label: 'ONE_TRACE' },
  { id: 'model', label: '模型治理' },
  { id: 'evaluation', label: '评测治理' },
];

function Coverage({ value }: { value: GovernanceCoverage }) {
  return <div className={value.complete ? 'governance-coverage complete' : 'governance-coverage partial'}>
    <b>{value.complete ? '数据覆盖完整' : '数据覆盖部分'}</b>
    <span>{value.source}</span>
    {value.warnings.map((warning) => <small key={warning}>{warning}</small>)}
  </div>;
}

const percent = (value?: number) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
const cny = (value: number) => `¥${value.toFixed(4)}`;

function CostView() {
  const [draft, setDraft] = useState<CostFilters>({});
  const [filters, setFilters] = useState<CostFilters>({});
  const result = useQuery({ queryKey: ['governance', 'cost', filters], queryFn: () => governanceApi.cost(filters) });
  if (result.isLoading) return <Loading />;
  if (!result.data) return <ErrorNotice error={result.error ?? new Error('成本台账不可用')} />;
  const data = result.data;
  return <>
    <Coverage value={data.coverage} />
    <form className="governance-filters" onSubmit={(event) => {
      event.preventDefault();
      setFilters({
        ...draft,
        from: draft.from ? new Date(draft.from).toISOString() : undefined,
        to: draft.to ? new Date(draft.to).toISOString() : undefined,
      });
    }}>
      <label>开始时间<input type="datetime-local" value={draft.from ?? ''} onChange={(event) => setDraft((value) => ({ ...value, from: event.target.value }))} /></label>
      <label>结束时间<input type="datetime-local" value={draft.to ?? ''} onChange={(event) => setDraft((value) => ({ ...value, to: event.target.value }))} /></label>
      <label>用户 ID<input value={draft.user_id ?? ''} onChange={(event) => setDraft((value) => ({ ...value, user_id: event.target.value }))} /></label>
      <label>会话 ID<input value={draft.conversation_id ?? ''} onChange={(event) => setDraft((value) => ({ ...value, conversation_id: event.target.value }))} /></label>
      <label>路由<input value={draft.route ?? ''} onChange={(event) => setDraft((value) => ({ ...value, route: event.target.value }))} /></label>
      <label>Provider<input value={draft.provider ?? ''} onChange={(event) => setDraft((value) => ({ ...value, provider: event.target.value }))} /></label>
      <label>模型<input value={draft.model ?? ''} onChange={(event) => setDraft((value) => ({ ...value, model: event.target.value }))} /></label>
      <div><button type="submit">应用筛选</button><button type="button" onClick={() => { setDraft({}); setFilters({}); }}>重置</button></div>
      <small>Workspace 由当前登录上下文强制限定，不允许跨工作区查询。</small>
    </form>
    <section className="governance-kpis">
      <article><small>调用数</small><strong>{data.requests}</strong></article>
      <article><small>总成本</small><strong>{cny(data.cost_cny)}</strong></article>
      <article><small>Token</small><strong>{(data.input_tokens + data.output_tokens).toLocaleString()}</strong></article>
      <article><small>平均延迟</small><strong>{data.average_latency_ms.toFixed(0)} ms</strong></article>
      <article><small>回退 / 错误</small><strong>{data.fallbacks} / {data.errors}</strong></article>
      <article><small>缓存命中</small><strong>{data.cache_hits}</strong></article>
      <article><small>高级模型升级</small><strong>{data.premium_escalations}</strong></article>
    </section>
    <section className="governance-grid">
      <article className="governance-card"><h2>用户分摊</h2><table><thead><tr><th>用户</th><th>调用</th><th>成本</th><th>错误</th></tr></thead><tbody>{data.by_user.map((item) => <tr key={item.key}><td><code>{item.key}</code></td><td>{item.requests}</td><td>{cny(item.cost_cny)}</td><td>{item.errors}</td></tr>)}</tbody></table></article>
      <article className="governance-card"><h2>会话分摊</h2><table><thead><tr><th>会话</th><th>调用</th><th>成本</th><th>延迟</th></tr></thead><tbody>{data.by_conversation.map((item) => <tr key={item.key}><td><code>{item.key}</code></td><td>{item.requests}</td><td>{cny(item.cost_cny)}</td><td>{item.average_latency_ms.toFixed(0)} ms</td></tr>)}</tbody></table></article>
      <article className="governance-card"><h2>Provider 分摊</h2><table><thead><tr><th>Provider</th><th>调用</th><th>成本</th><th>延迟</th></tr></thead><tbody>{data.by_provider.map((item) => <tr key={item.key}><td>{item.key}</td><td>{item.requests}</td><td>{cny(item.cost_cny)}</td><td>{item.average_latency_ms.toFixed(0)} ms</td></tr>)}</tbody></table></article>
      <article className="governance-card"><h2>模型分摊</h2><table><thead><tr><th>模型</th><th>调用</th><th>Token</th><th>成本</th></tr></thead><tbody>{data.by_model.map((item) => <tr key={item.key}><td>{item.key}</td><td>{item.requests}</td><td>{item.input_tokens + item.output_tokens}</td><td>{cny(item.cost_cny)}</td></tr>)}</tbody></table></article>
      <article className="governance-card"><h2>路由分摊</h2><table><thead><tr><th>路由</th><th>调用</th><th>回退</th><th>错误</th></tr></thead><tbody>{data.by_route.map((item) => <tr key={item.key}><td>{item.key}</td><td>{item.requests}</td><td>{item.fallbacks}</td><td>{item.errors}</td></tr>)}</tbody></table></article>
    </section>
    <section className="governance-card governance-wide"><h2>最近调用台账</h2><div className="governance-table-scroll"><table><thead><tr><th>Trace</th><th>路由</th><th>Provider / Model</th><th>Token</th><th>成本</th><th>延迟</th><th>状态</th></tr></thead><tbody>{data.entries.map((item) => <tr key={item.id}><td><code>{item.trace_id}</code></td><td>{item.route ?? 'UNKNOWN'}</td><td>{item.provider} / {item.model}</td><td>{item.input_tokens + item.output_tokens}</td><td>{cny(item.cost_cny)}</td><td>{item.latency_ms} ms</td><td>{item.status}</td></tr>)}</tbody></table></div></section>
  </>;
}

function TraceView() {
  const [selectedTraceId, setSelectedTraceId] = useState('');
  const result = useQuery({ queryKey: ['governance', 'trace'], queryFn: governanceApi.traces });
  const detail = useQuery({
    queryKey: ['governance', 'trace', selectedTraceId],
    queryFn: () => governanceApi.trace(selectedTraceId),
    enabled: Boolean(selectedTraceId),
  });
  if (result.isLoading) return <Loading />;
  if (!result.data) return <ErrorNotice error={result.error ?? new Error('Trace 不可用')} />;
  return <><Coverage value={result.data.coverage} /><section className="governance-card governance-wide"><div className="governance-card-heading"><h2>ONE_TRACE 时序索引</h2><span>{result.data.trace_granularity}</span></div><div className="governance-table-scroll"><table><thead><tr><th>Trace ID</th><th>路由</th><th>状态</th><th>阶段</th><th>耗时</th><th>Provider / Model</th><th>能力 / Artifact</th><th>错误</th></tr></thead><tbody>{result.data.items.map((item) => <tr key={item.trace_id}><td><button className="governance-trace-link" type="button" onClick={() => setSelectedTraceId(item.trace_id)}><code>{item.trace_id}</code></button></td><td>{item.route ?? 'UNKNOWN'}</td><td>{item.status}</td><td>{item.stage_count}</td><td>{item.duration_ms} ms</td><td>{item.provider ?? '—'} / {item.model ?? '—'}</td><td>{[item.has_sql && 'SQL', item.has_rag && 'RAG', item.has_agent && 'AGENT', item.has_file && 'FILE', item.has_vision && 'VISION'].filter(Boolean).join(' · ') || '—'} · {item.artifact_count}</td><td>{item.error_code ?? '—'}</td></tr>)}</tbody></table></div></section>
    {selectedTraceId && <section className="governance-card governance-wide"><div className="governance-card-heading"><h2>Trace 阶段详情</h2><button type="button" onClick={() => setSelectedTraceId('')}>关闭</button></div>{detail.isLoading ? <Loading /> : !detail.data ? <ErrorNotice error={detail.error ?? new Error('Trace 详情不可用')} /> : <div className="governance-table-scroll"><table><thead><tr><th>阶段</th><th>开始</th><th>耗时</th><th>状态</th><th>Provider / Model</th><th>Tool</th><th>SQL</th><th>错误</th></tr></thead><tbody>{detail.data.stages.map((stage, index) => <tr key={`${stage.stage}:${stage.started_at}:${index}`}><td><b>{stage.stage}</b><small>{stage.timing_source}</small></td><td>{new Date(stage.started_at).toLocaleString('zh-CN')}</td><td>{stage.duration_ms} ms</td><td>{stage.status}</td><td>{stage.provider ?? '—'} / {stage.model ?? '—'}</td><td>{stage.tool ?? '—'}</td><td>{stage.sql ? <details><summary>查看</summary><code>{stage.sql}</code></details> : '—'}</td><td>{stage.error_code ?? '—'}</td></tr>)}</tbody></table></div>}</section>}
  </>;
}

function ModelView() {
  const result = useQuery({ queryKey: ['governance', 'models'], queryFn: governanceApi.models });
  if (result.isLoading) return <Loading />;
  if (!result.data) return <ErrorNotice error={result.error ?? new Error('模型治理数据不可用')} />;
  return <><Coverage value={result.data.coverage} /><section className="governance-model-grid">{result.data.providers.map((item) => <article className="governance-card governance-model-card" key={item.provider}><header><div><h2>{item.display_name}</h2><small>{item.model ?? '未配置模型'}</small></div><span className={item.health === 'HEALTHY' ? 'healthy' : 'neutral'}>{item.health}</span></header><dl><div><dt>熔断状态</dt><dd>{item.circuit_state}</dd></div><div><dt>调用 / 错误</dt><dd>{item.requests} / {item.errors}</dd></div><div><dt>平均延迟</dt><dd>{item.average_latency_ms.toFixed(0)} ms</dd></div><div><dt>成本</dt><dd>{cny(item.cost_cny)}</dd></div><div><dt>回退率</dt><dd>{percent(item.fallback_rate)}</dd></div><div><dt>升级率</dt><dd>{percent(item.premium_ratio)}</dd></div></dl></article>)}</section><section className="governance-card governance-wide"><h2>路由政策</h2><p className="governance-muted">价格版本：{result.data.pricing_version}</p>{Object.entries(result.data.default_routes).map(([route, providers]) => <div className="governance-route" key={route}><b>{route}</b><span>{providers.join(' → ')}</span></div>)}</section></>;
}

function EvaluationView() {
  const result = useQuery({ queryKey: ['governance', 'evaluation'], queryFn: governanceApi.evaluation });
  if (result.isLoading) return <Loading />;
  if (!result.data) return <ErrorNotice error={result.error ?? new Error('评测治理数据不可用')} />;
  return <><Coverage value={result.data.coverage} /><section className="governance-card governance-wide"><div className="governance-card-heading"><h2>评测套件与证据</h2><Link className="button secondary" to="/evaluation">进入评测中心</Link></div><div className="governance-table-scroll"><table><thead><tr><th>套件</th><th>来源</th><th>版本 / SHA</th><th>状态</th><th>通过率</th><th>结果准确率</th><th>引用准确率</th><th>实际调用</th><th>Artifacts</th></tr></thead><tbody>{result.data.runs.map((item) => <tr key={item.id}><td><b>{item.suite}</b>{item.errors.length > 0 && <small>{item.errors.join('；')}</small>}</td><td>{item.source}</td><td>{item.version ?? '—'}<small>{item.source_sha?.slice(0, 12) ?? '—'}</small></td><td>{item.status}</td><td>{percent(item.pass_rate)}</td><td>{percent(item.result_accuracy)}</td><td>{percent(item.citation_accuracy)}</td><td>{item.runtime_calls ?? '—'}</td><td>{item.artifacts.length ? <details><summary>{item.artifacts.length} 个</summary>{item.artifacts.map((artifact) => <small key={artifact}>{artifact}</small>)}</details> : '—'}</td></tr>)}</tbody></table></div></section></>;
}

export function GovernanceCenterPage({ view }: { view: GovernanceView }) {
  const navigate = useNavigate();
  const title = views.find((item) => item.id === view)?.label ?? '治理中心';
  return <div className="settings-surface-page governance-page" data-testid="governance-center-page">
    <header className="settings-page-heading"><div><h1>{title}</h1><p>成本、Trace、模型和评测均来自 Backend 持久化证据，不暴露提示词、思考过程或凭据。</p></div></header>
    <nav className="governance-nav" aria-label="治理中心分区"><button type="button" onClick={() => navigate('/settings/models')}>模型配置</button>{views.map((item) => <button key={item.id} type="button" className={item.id === view ? 'active' : ''} onClick={() => navigate(`/settings/models?view=${item.id}`)}>{item.label}</button>)}</nav>
    {view === 'cost' && <CostView />}
    {view === 'trace' && <TraceView />}
    {view === 'model' && <ModelView />}
    {view === 'evaluation' && <EvaluationView />}
  </div>;
}
