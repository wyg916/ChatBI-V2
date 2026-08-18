import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { dataWorkspaceApi, type SqlWorkspaceRun } from '../api/dataWorkspace';
import { datasourceApi } from '../api/datasources';
import { ErrorNotice, Loading, PageHeading, StatusBadge } from '../components/UI';
import { useDatasource, useSchemas, useTables } from '../hooks/useData';
import './data-workspace.css';

type Tab = 'catalog' | 'sql' | 'history';

function resultTable(run?: SqlWorkspaceRun) {
  const columns = run?.execution.columns ?? [];
  const rows = run?.execution.rows ?? [];
  if (!columns.length) return <div className="workspace-empty">执行后在这里展示只读结果。</div>;
  return <div className="workspace-result-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>
    {rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{typeof row[column] === 'object' ? JSON.stringify(row[column]) : String(row[column] ?? '—')}</td>)}</tr>)}
  </tbody></table></div>;
}

export function DataWorkspacePage() {
  const { id = '' } = useParams();
  const client = useQueryClient();
  const source = useDatasource(id);
  const schemas = useSchemas(id);
  const [tab, setTab] = useState<Tab>('catalog');
  const [schema, setSchema] = useState('');
  const activeSchema = schema || source.data?.schema || schemas.data?.[0]?.name || '';
  const tables = useTables(id, activeSchema);
  const [table, setTable] = useState('');
  const [search, setSearch] = useState('');
  const [searchKind, setSearchKind] = useState('all');
  const [samplePage, setSamplePage] = useState(1);
  const [sampleEnabled, setSampleEnabled] = useState(false);
  const [sql, setSql] = useState('');
  const [result, setResult] = useState<SqlWorkspaceRun>();
  const [notice, setNotice] = useState('');
  const tableColumns = useQuery({
    queryKey: ['data-workspace-columns', id, activeSchema, table],
    queryFn: () => datasourceApi.columns(id, table, activeSchema), enabled: Boolean(id && activeSchema && table),
  });

  useEffect(() => {
    if (!schema && schemas.data?.length) setSchema(source.data?.schema || schemas.data[0].name);
  }, [schema, schemas.data, source.data?.schema]);
  useEffect(() => {
    if (tables.data?.length && !tables.data.some((item) => item.name === table)) setTable(tables.data[0].name);
  }, [table, tables.data]);
  useEffect(() => {
    setSampleEnabled(false); setSamplePage(1);
    if (activeSchema && table && tableColumns.data?.length) {
      const names = tableColumns.data.slice(0, 12).map((column) => column.name).join(',\n  ');
      setSql(`SELECT\n  ${names}\nFROM ${activeSchema}.${table}\nLIMIT 100`);
    }
  }, [activeSchema, table, tableColumns.data]);

  const catalog = useQuery({
    queryKey: ['data-workspace-search', id, search, searchKind],
    queryFn: () => dataWorkspaceApi.search(id, search, searchKind), enabled: Boolean(id),
  });
  const relations = useQuery({
    queryKey: ['data-workspace-relationships', id], queryFn: () => dataWorkspaceApi.relationships(id), enabled: Boolean(id),
  });
  const sample = useQuery({
    queryKey: ['data-workspace-sample', id, activeSchema, table, samplePage],
    queryFn: () => dataWorkspaceApi.sample(id, activeSchema, table, samplePage, 50),
    enabled: sampleEnabled && Boolean(id && activeSchema && table),
  });
  const history = useQuery({
    queryKey: ['data-workspace-history', id], queryFn: () => dataWorkspaceApi.history(id), enabled: Boolean(id),
  });

  const format = useMutation({ mutationFn: () => dataWorkspaceApi.format(id, sql), onSuccess: (data) => setSql(data.formatted_sql) });
  const execute = useMutation({ mutationFn: () => dataWorkspaceApi.execute(id, sql), onSuccess: (data) => { setResult(data); setTab('sql'); client.invalidateQueries({ queryKey: ['data-workspace-history', id] }); } });
  const explain = useMutation({ mutationFn: () => dataWorkspaceApi.explain(id, sql), onSuccess: (data) => { setResult(data); setTab('sql'); client.invalidateQueries({ queryKey: ['data-workspace-history', id] }); } });
  const replay = useMutation({ mutationFn: (runId: string) => dataWorkspaceApi.replay(runId), onSuccess: (data) => { setSql(data.sql_text); setResult(data); setTab('sql'); client.invalidateQueries({ queryKey: ['data-workspace-history', id] }); } });
  const verify = useMutation({ mutationFn: (runId: string) => dataWorkspaceApi.verify(runId), onSuccess: (data) => { setNotice(`Verified SQL 已保存到答案库：${data.answer_id.slice(0, 8)}`); client.invalidateQueries({ queryKey: ['data-workspace-history', id] }); } });

  const error = source.error ?? schemas.error ?? tables.error ?? tableColumns.error ?? catalog.error ?? relations.error ?? sample.error ?? history.error ?? format.error ?? execute.error ?? explain.error ?? replay.error ?? verify.error;
  const selectedRelations = useMemo(() => (relations.data ?? []).filter((item) => item.source_table === table || item.target_table === table), [relations.data, table]);

  if (source.isLoading || schemas.isLoading) return <Loading />;
  if (!source.data) return <ErrorNotice error={source.error ?? new Error('未找到数据源')} />;

  return <section className="data-workspace-page" data-testid="data-workspace-page">
    <PageHeading title="数据工作台" description={`${source.data.name} · ${source.data.type === 'postgresql' ? 'PostgreSQL' : 'MySQL'} · 全链路只读安全执行`} actions={<Link className="button secondary" to={`/datasources/${id}`}>返回 Schema 管理</Link>} />
    {notice && <div className="notice success" role="status">{notice}</div>}
    <ErrorNotice error={error} />
    <div className="workspace-tabs" role="tablist">
      <button className={tab === 'catalog' ? 'active' : ''} onClick={() => setTab('catalog')}>目录浏览</button>
      <button className={tab === 'sql' ? 'active' : ''} onClick={() => setTab('sql')}>SQL 工作区</button>
      <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>查询历史</button>
    </div>

    {tab === 'catalog' && <div className="catalog-workspace">
      <aside className="workspace-tree">
        <label>Schema<select aria-label="工作台 Schema" value={activeSchema} onChange={(event) => { setSchema(event.target.value); setTable(''); }}>
          {(schemas.data ?? []).map((item) => <option key={item.name} value={item.name}>{item.name} ({item.table_count})</option>)}
        </select></label>
        <strong>数据表</strong>
        <div className="workspace-table-list">{(tables.data ?? []).map((item) => <button data-testid="workspace-table" className={table === item.name ? 'active' : ''} key={item.id} onClick={() => setTable(item.name)}><span>{item.name}</span><small>{item.column_count} 字段</small></button>)}</div>
      </aside>
      <main className="catalog-main">
        <header className="catalog-search"><input aria-label="搜索 Schema 表或字段" placeholder="搜索 Schema、表、字段" value={search} onChange={(event) => setSearch(event.target.value)} /><select value={searchKind} onChange={(event) => setSearchKind(event.target.value)}><option value="all">全部对象</option><option value="schema">Schema</option><option value="table">表</option><option value="column">字段</option></select><span>{catalog.data?.total ?? 0} 项</span></header>
        <div className="catalog-results">{(catalog.data?.items ?? []).map((item) => <article key={`${item.kind}-${item.id}`}><span>{item.kind.toUpperCase()}</span><div><strong>{item.name}</strong><small>{item.qualified_name}{item.data_type ? ` · ${item.data_type}` : ''}</small></div>{item.primary_key && <em>PK</em>}{item.foreign_key && <em>FK</em>}</article>)}</div>
      </main>
      <aside className="sample-panel">
        <h2>{activeSchema}.{table}</h2>
        <button className="button primary" disabled={!table || sample.isFetching} onClick={() => setSampleEnabled(true)}>{sample.isFetching ? '读取中…' : '懒加载样例值'}</button>
        {sample.data && <><small>第 {sample.data.page} 页 · {sample.data.row_count} 行 · 脱敏字段 {sample.data.masked_columns.length}</small><div className="mini-table">{sample.data.rows.slice(0, 8).map((row, index) => <pre key={index}>{JSON.stringify(row, null, 2)}</pre>)}</div><footer><button disabled={samplePage === 1} onClick={() => setSamplePage((page) => page - 1)}>上一页</button><button disabled={sample.data.row_count < sample.data.page_size} onClick={() => setSamplePage((page) => page + 1)}>下一页</button></footer></>}
        <h3>关系</h3>{selectedRelations.length ? selectedRelations.map((item) => <p key={item.id}>{item.source_table}.{item.source_columns.join(',')} → {item.target_table}.{item.target_columns.join(',')}</p>) : <p>当前表没有同步到外键关系。</p>}
      </aside>
    </div>}

    {tab === 'sql' && <div className="sql-workspace">
      <section className="sql-editor-panel"><header><div><strong>只读 SQL Editor</strong><small>SQLGlot Guard → 权限校验 → Query Executor → Result Oracle</small></div><StatusBadge status={result?.status ?? 'READY'} /></header><textarea aria-label="SQL 编辑器" value={sql} onChange={(event) => setSql(event.target.value)} spellCheck={false} /><footer><button className="button secondary" disabled={format.isPending} onClick={() => format.mutate()}>格式化</button><button className="button secondary" disabled={explain.isPending} onClick={() => explain.mutate()}>Explain</button><button className="button primary" data-testid="execute-sql" disabled={execute.isPending} onClick={() => execute.mutate()}>执行只读查询</button></footer></section>
      <section className="sql-result-panel"><header><div><strong>执行结果</strong><small>{result ? `${result.operation} · ${result.duration_ms ?? 0} ms · ${(result.execution.result_signature ?? '').slice(0, 12)}` : '尚未执行'}</small></div>{result?.status === 'SUCCEEDED' && <button className="button secondary" onClick={() => verify.mutate(result.id)}>保存为 Verified SQL</button>}</header>{result?.status === 'SECURITY_REJECTED' ? <div className="notice error">安全策略拒绝：{result.error_code} {result.error_message}</div> : resultTable(result)}</section>
    </div>}

    {tab === 'history' && <section className="workspace-history"><header><h2>我的查询历史</h2><span>{history.data?.total ?? 0} 条</span></header>{(history.data?.items ?? []).map((run) => <article key={run.id}><div><strong>{run.operation} · {run.status}</strong><code>{run.normalized_sql ?? run.sql_text}</code><small>{new Date(run.created_at).toLocaleString('zh-CN', { hour12: false })} · {run.duration_ms ?? 0} ms</small></div><footer><button onClick={() => replay.mutate(run.id)}>重放</button>{run.status === 'SUCCEEDED' && <button disabled={Boolean(run.verified_answer_id)} onClick={() => verify.mutate(run.id)}>{run.verified_answer_id ? '已验证' : '保存 Verified SQL'}</button>}</footer></article>)}</section>}
  </section>;
}
