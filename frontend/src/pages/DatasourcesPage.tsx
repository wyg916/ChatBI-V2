import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { datasourceApi } from '../api/datasources';
import { useDatasources } from '../hooks/useData';
import type { DatasourceInput, DatasourceKind } from '../types/api';
import { ErrorNotice, Field, FormActions, Loading, Modal, PageHeading, StatusBadge } from '../components/UI';

const defaultForm: DatasourceInput = { name: '', type: 'postgresql', host: 'localhost', port: 5432, database: '', username: '', password: '', schema: 'public', ssl: false };

export function DatasourcesPage() {
  const { data = [], isLoading, error } = useDatasources();
  const client = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(defaultForm);
  const [search, setSearch] = useState('');
  const [feedback, setFeedback] = useState('');
  const filtered = useMemo(() => data.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())), [data, search]);
  const create = useMutation({
    mutationFn: async (input: DatasourceInput) => { const saved = await datasourceApi.create(input); const test = await datasourceApi.test(saved.id); return { saved, test }; },
    onSuccess: ({ saved, test }) => { client.invalidateQueries({ queryKey: ['datasources'] }); setShowCreate(false); setForm(defaultForm); setFeedback(`${saved.name} 已保存，连接${test.success ? '测试通过' : '测试未通过'}`); },
  });
  const sync = useMutation({ mutationFn: datasourceApi.sync, onSuccess: (_, id) => { client.invalidateQueries({ queryKey: ['datasources'] }); setFeedback(`数据源 ${id} 元数据同步完成`); } });
  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate(form); };
  const changeType = (type: DatasourceKind) => setForm((old) => ({ ...old, type, port: type === 'postgresql' ? 5432 : 3306, schema: type === 'postgresql' ? 'public' : undefined }));
  const totals = data.reduce((sum, item) => ({ tables: sum.tables + (item.table_count ?? 0), columns: sum.columns + (item.column_count ?? 0) }), { tables: 0, columns: 0 });
  return <>
    <PageHeading title="数据源" description="连接和管理您的数据源，统一管理 Schema、字段和访问权限。" actions={<><button className="button secondary" onClick={() => data.forEach((item) => sync.mutate(item.id))}>↻ 同步全部数据源</button><button className="button primary" data-testid="create-datasource" onClick={() => setShowCreate(true)}>＋ 新建数据源</button></>} />
    {feedback && <div className="notice success">{feedback}</div>}<ErrorNotice error={error ?? create.error ?? sync.error} />
    <div className="summary-grid"><article><span>源</span><small>数据源总数</small><strong>{data.length}</strong></article><article><span>连</span><small>正常连接</small><strong>{data.filter((item) => item.status === 'CONNECTED').length}</strong></article><article><span>表</span><small>可用数据表</small><strong>{totals.tables}</strong></article><article><span>列</span><small>字段数量</small><strong>{totals.columns}</strong></article></div>
    <div className="filterbar"><input aria-label="搜索数据源" placeholder="⌕  搜索数据源名称" value={search} onChange={(event) => setSearch(event.target.value)} /><span>共 {filtered.length} 个数据源</span></div>
    {isLoading ? <Loading /> : <div className="datasource-grid">{filtered.map((item) => <article className="datasource-card" key={item.id} data-testid="datasource-card"><Link to={`/datasources/${item.id}`}><div className={`db-icon ${item.type}`}>{item.type === 'postgresql' ? 'PG' : 'MY'}</div><div><h2>{item.name}</h2><strong>{item.type === 'postgresql' ? 'PostgreSQL' : 'MySQL'}</strong><p>{item.host}:{item.port} / {item.database}</p></div><StatusBadge status={item.status} /></Link><div className="card-stats"><span><strong>{item.table_count ?? 0}</strong><small>数据表</small></span><span><strong>{item.column_count ?? 0}</strong><small>字段数量</small></span><button className="button small secondary" onClick={() => sync.mutate(item.id)}>同步</button></div></article>)}</div>}
    {!isLoading && filtered.length === 0 && <div className="empty-card"><span>源</span><h2>还没有数据源</h2><p>连接 PostgreSQL 或 MySQL，开始同步业务元数据。</p><button className="button primary" onClick={() => setShowCreate(true)}>新建数据源</button></div>}
    {showCreate && <Modal title="新建数据源" onClose={() => setShowCreate(false)}><form className="form-grid" onSubmit={submit}><div className="type-picker"><button type="button" className={form.type === 'postgresql' ? 'selected' : ''} onClick={() => changeType('postgresql')}><b>PG</b>PostgreSQL</button><button type="button" className={form.type === 'mysql' ? 'selected' : ''} onClick={() => changeType('mysql')}><b>MY</b>MySQL</button></div><Field label="数据源名称"><input name="name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}/></Field><div className="form-columns"><Field label="Host"><input name="host" required value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })}/></Field><Field label="Port"><input name="port" type="number" required value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}/></Field></div><Field label="Database"><input name="database" required value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })}/></Field><div className="form-columns"><Field label="Username"><input name="username" required autoComplete="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}/></Field><Field label="Password"><input name="password" type="password" required autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}/></Field></div>{form.type === 'postgresql' && <Field label="默认 Schema"><input value={form.schema} onChange={(e) => setForm({ ...form, schema: e.target.value })}/></Field>}<label className="check-row"><input type="checkbox" checked={form.ssl} onChange={(e) => setForm({ ...form, ssl: e.target.checked })}/>启用 SSL 加密连接</label><ErrorNotice error={create.error}/><FormActions busy={create.isPending} onCancel={() => setShowCreate(false)} submitLabel="保存并测试连接" /></form></Modal>}
  </>;
}
