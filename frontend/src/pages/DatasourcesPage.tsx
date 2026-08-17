import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { datasourceApi } from '../api/datasources';
import { useDatasources } from '../hooks/useData';
import type { Datasource, DatasourceInput, DatasourceKind } from '../types/api';
import { ErrorNotice, Field, FormActions, Loading, Modal, PageHeading, StatusBadge } from '../components/UI';
import './datasources.css';

const defaultForm: DatasourceInput = {
  name: '', type: 'postgresql', host: 'localhost', port: 5432,
  database: '', username: '', password: '', schema: 'public', ssl: false,
};

const normalStatuses = new Set(['CONNECTED', 'SYNCED']);

function isNormal(item: Datasource) {
  return normalStatuses.has(item.status ?? '');
}

function datasourceType(item: Datasource) {
  return item.type === 'postgresql'
    ? { mark: 'PG', product: 'PostgreSQL', version: 'PostgreSQL' }
    : { mark: 'MY', product: 'MySQL', version: 'MySQL' };
}

function formatRelativeTime(value?: string) {
  if (!value) return '尚未同步';
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return '尚未同步';
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return '刚刚';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return days < 30 ? `${days} 天前` : new Date(value).toLocaleDateString('zh-CN');
}

export function DatasourcesPage() {
  const { data = [], isLoading, error } = useDatasources();
  const client = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(defaultForm);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<'all' | DatasourceKind>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'normal' | 'attention'>('all');
  const [feedback, setFeedback] = useState('');

  const filtered = useMemo(() => data.filter((item) => {
    const text = `${item.name} ${item.type} ${item.database}`.toLowerCase();
    const matchesSearch = text.includes(search.trim().toLowerCase());
    const matchesType = typeFilter === 'all' || item.type === typeFilter;
    const matchesStatus = statusFilter === 'all'
      || (statusFilter === 'normal' && isNormal(item))
      || (statusFilter === 'attention' && !isNormal(item));
    return matchesSearch && matchesType && matchesStatus;
  }), [data, search, typeFilter, statusFilter]);

  const create = useMutation({
    mutationFn: async (input: DatasourceInput) => {
      const saved = await datasourceApi.create(input);
      const test = await datasourceApi.test(saved.id);
      return { saved, test };
    },
    onSuccess: ({ saved, test }) => {
      client.invalidateQueries({ queryKey: ['datasources'] });
      setShowCreate(false);
      setForm(defaultForm);
      setFeedback(`${saved.name} 已保存，连接${test.success ? '测试通过' : '测试未通过'}`);
    },
  });

  const syncAll = useMutation({
    mutationFn: async () => {
      const results = await Promise.all(data.map(async (item) => ({ item, result: await datasourceApi.sync(item.id) })));
      const failed = results.filter(({ result }) => result.success === false);
      if (failed.length) throw new Error(`${failed.map(({ item }) => item.name).join('、')} 同步未成功，请检查连接设置`);
      return results.length;
    },
    onSuccess: (count) => {
      client.invalidateQueries({ queryKey: ['datasources'] });
      setFeedback(count ? `已完成 ${count} 个数据源的元数据同步` : '当前没有可同步的数据源');
    },
  });

  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate(form); };
  const changeType = (type: DatasourceKind) => setForm((old) => ({
    ...old, type, port: type === 'postgresql' ? 5432 : 3306,
    schema: type === 'postgresql' ? 'public' : undefined,
  }));

  const totals = data.reduce((sum, item) => ({
    tables: sum.tables + (item.table_count ?? 0),
    columns: sum.columns + (item.column_count ?? 0),
  }), { tables: 0, columns: 0 });
  const latestSync = data.reduce<string | undefined>((latest, item) => {
    const value = item.last_sync_at ?? item.last_synced_at;
    if (!value) return latest;
    return !latest || new Date(value) > new Date(latest) ? value : latest;
  }, undefined);

  return <section className="datasource-page">
    <PageHeading
      title="数据源"
      description="连接和管理您的数据源，统一管理 Schema、字段和访问权限。"
      actions={<>
        <button className="button secondary" disabled={syncAll.isPending} onClick={() => syncAll.mutate()}>
          {syncAll.isPending ? '正在同步…' : '↻ 同步全部数据源'}
        </button>
        <button className="button primary" data-testid="create-datasource" onClick={() => setShowCreate(true)}>＋ 新建数据源</button>
      </>}
    />

    {feedback && <div className="notice success" role="status">{feedback}</div>}
    <ErrorNotice error={error ?? create.error ?? syncAll.error} />

    <div className="summary-grid datasource-summary-grid" aria-label="数据源概览">
      <article><span>源</span><small>数据源总数</small><strong>{data.length}</strong></article>
      <article><span>连</span><small>正常连接</small><div><strong>{data.filter(isNormal).length}</strong><em>运行正常</em></div></article>
      <article><span>表</span><small>可用数据表</small><strong>{totals.tables}</strong></article>
      <article><span>时</span><small>最近同步</small><strong className="relative-time">{formatRelativeTime(latestSync)}</strong></article>
    </div>

    <div className="datasource-filterbar">
      <label className="datasource-search"><span aria-hidden="true">⌕</span><input aria-label="搜索数据源" placeholder="搜索数据源名称或数据库" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <select aria-label="数据源类型" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as 'all' | DatasourceKind)}>
        <option value="all">全部类型</option><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option>
      </select>
      <select aria-label="连接状态" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as 'all' | 'normal' | 'attention')}>
        <option value="all">全部状态</option><option value="normal">运行正常</option><option value="attention">需要关注</option>
      </select>
      <span>共 {filtered.length} 个数据源{latestSync ? ` · 更新于 ${formatRelativeTime(latestSync)}` : ''}</span>
    </div>

    {isLoading ? <Loading /> : <div className="datasource-grid">
      {filtered.map((item) => {
        const type = datasourceType(item);
        return <article className="datasource-card" key={item.id} data-testid="datasource-card">
          <Link to={`/datasources/${item.id}`} aria-label={`打开数据源 ${item.name}`}>
            <div className={`db-icon ${item.type}`}>{type.mark}</div>
            <div className="datasource-card-title"><h2>{item.name}</h2><strong>{type.product}</strong><p>{type.version} · {item.database}</p></div>
            <StatusBadge status={item.status} />
          </Link>
          <div className="card-stats">
            <span><strong>{item.table_count ?? 0}</strong><small>数据表</small></span>
            <span><strong>{item.column_count ?? 0}</strong><small>字段数量</small></span>
            <span><strong>{formatRelativeTime(item.last_sync_at ?? item.last_synced_at)}</strong><small>最近同步</small></span>
          </div>
        </article>;
      })}
    </div>}

    {!isLoading && filtered.length === 0 && <div className="empty-card">
      <span>源</span><h2>{data.length ? '没有符合条件的数据源' : '还没有数据源'}</h2>
      <p>{data.length ? '请调整搜索词或筛选条件。' : '连接 PostgreSQL 或 MySQL，开始同步业务元数据。'}</p>
      {!data.length && <button className="button primary" onClick={() => setShowCreate(true)}>新建数据源</button>}
    </div>}

    {showCreate && <Modal title="新建数据源" onClose={() => setShowCreate(false)}>
      <form className="form-grid" onSubmit={submit}>
        <p className="form-intro">凭据只提交给 Backend API 并加密保存，浏览器不会直接连接数据库。</p>
        <div className="type-picker">
          <button type="button" className={form.type === 'postgresql' ? 'selected' : ''} onClick={() => changeType('postgresql')}><b>PG</b>PostgreSQL</button>
          <button type="button" className={form.type === 'mysql' ? 'selected' : ''} onClick={() => changeType('mysql')}><b>MY</b>MySQL</button>
        </div>
        <Field label="数据源名称"><input name="name" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
        <div className="form-columns">
          <Field label="Host"><input name="host" required value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} /></Field>
          <Field label="Port"><input name="port" type="number" required value={form.port} onChange={(event) => setForm({ ...form, port: Number(event.target.value) })} /></Field>
        </div>
        <Field label="Database"><input name="database" required value={form.database} onChange={(event) => setForm({ ...form, database: event.target.value })} /></Field>
        <div className="form-columns">
          <Field label="Username"><input name="username" required autoComplete="username" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></Field>
          <Field label="Password"><input name="password" type="password" required autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></Field>
        </div>
        {form.type === 'postgresql' && <Field label="默认 Schema"><input value={form.schema} onChange={(event) => setForm({ ...form, schema: event.target.value })} /></Field>}
        <label className="check-row"><input type="checkbox" checked={form.ssl} onChange={(event) => setForm({ ...form, ssl: event.target.checked })} />启用 SSL 加密连接</label>
        <ErrorNotice error={create.error} />
        <FormActions busy={create.isPending} onCancel={() => setShowCreate(false)} submitLabel="保存并测试连接" />
      </form>
    </Modal>}
  </section>;
}
