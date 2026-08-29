import { useDeferredValue, useEffect, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { datasourceApi } from '../api/datasources';
import { useColumns, useDatasource, useSchemas, useTables } from '../hooks/useData';
import { ErrorNotice, Field, FormActions, Loading, Modal, PageHeading, StatusBadge } from '../components/UI';
import type { ColumnInfo, DatasourceUpdateInput } from '../types/api';
import './datasources.css';

type EditForm = Required<Pick<DatasourceUpdateInput, 'name' | 'host' | 'port' | 'database' | 'username' | 'schema' | 'ssl'>> & { password: string };

const emptyEditForm: EditForm = {
  name: '', host: '', port: 5432, database: '', username: '', schema: '', ssl: false, password: '',
};

function columnRole(column: ColumnInfo) {
  if (column.primary_key || column.is_primary_key) return '主键';
  if (column.foreign_key || column.is_foreign_key) return '外键';
  const type = (column.type ?? column.data_type ?? '').toLowerCase();
  if (/date|time/.test(type)) return '时间';
  if (/int|decimal|numeric|float|double|real|money/.test(type)) return '度量';
  return '维度';
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '--';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function formatSyncTime(value?: string) {
  if (!value) return '尚未同步';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '尚未同步' : date.toLocaleString('zh-CN', { hour12: false });
}

export function DatasourceDetailPage() {
  const { id = '' } = useParams();
  const client = useQueryClient();
  const source = useDatasource(id);
  const schemas = useSchemas(id);
  const [selectedSchema, setSelectedSchema] = useState('');
  const activeSchema = selectedSchema || source.data?.schema || schemas.data?.[0]?.name || '';
  const allTables = useTables(id, activeSchema);
  const [selected, setSelected] = useState('');
  const [tableSearch, setTableSearch] = useState('');
  const deferredTableSearch = useDeferredValue(tableSearch);
  const tables = useTables(id, activeSchema, deferredTableSearch);
  const [message, setMessage] = useState('');
  const [showEdit, setShowEdit] = useState(false);
  const [editForm, setEditForm] = useState<EditForm>(emptyEditForm);

  useEffect(() => {
    if (!selectedSchema && schemas.data?.length) {
      const preferred = schemas.data.find((item) => item.name === source.data?.schema)?.name;
      setSelectedSchema(preferred ?? schemas.data[0].name);
    }
  }, [schemas.data, selectedSchema, source.data?.schema]);

  useEffect(() => {
    if (!allTables.data?.length) {
      setSelected('');
      return;
    }
    if (!allTables.data.some((table) => table.name === selected)) setSelected(allTables.data[0].name);
  }, [selected, allTables.data]);

  const columns = useColumns(id, selected, activeSchema);
  const currentTable = allTables.data?.find((table) => table.name === selected);
  const filteredTables = tables.data ?? [];
  const previewColumns = (columns.data ?? []).slice(0, 5);
  const sampleCount = Math.min(5, Math.max(0, ...previewColumns.map((column) => column.sample_values?.length ?? 0)));
  const sampleRows = Array.from({ length: sampleCount }, (_, rowIndex) => previewColumns.map((column) => column.sample_values?.[rowIndex]));

  const test = useMutation({
    mutationFn: () => datasourceApi.test(id),
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['datasource', id] });
      client.invalidateQueries({ queryKey: ['datasources'] });
      setMessage(data.message ?? (data.success ? '连接测试通过' : '连接测试失败'));
    },
  });

  const sync = useMutation({
    mutationFn: () => datasourceApi.sync(id),
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['schemas', id] });
      client.invalidateQueries({ queryKey: ['tables', id] });
      client.invalidateQueries({ queryKey: ['columns', id] });
      client.invalidateQueries({ queryKey: ['datasource', id] });
      client.invalidateQueries({ queryKey: ['datasources'] });
      setMessage(data.success === false ? 'Schema 同步未成功，请检查连接设置' : `Schema 与字段元数据同步完成${data.tables !== undefined ? `：${data.tables} 张表、${data.columns ?? 0} 个字段` : ''}`);
    },
  });

  const update = useMutation({
    mutationFn: () => {
      if (source.data?.type === 'excel') return datasourceApi.update(id, { name: editForm.name });
      const { password, ...values } = editForm;
      return datasourceApi.update(id, password ? { ...values, password } : values);
    },
    onSuccess: (saved) => {
      client.setQueryData(['datasource', id], saved);
      client.invalidateQueries({ queryKey: ['datasources'] });
      setShowEdit(false);
      setMessage('数据源设置已更新');
    },
  });

  const openEdit = () => {
    if (!source.data) return;
    setEditForm({
      name: source.data.name,
      host: source.data.host,
      port: source.data.port,
      database: source.data.database,
      username: source.data.username,
      schema: source.data.schema ?? '',
      ssl: source.data.ssl ?? false,
      password: '',
    });
    setShowEdit(true);
  };

  const submitEdit = (event: FormEvent) => { event.preventDefault(); update.mutate(); };

  if (source.isLoading || schemas.isLoading || allTables.isLoading) return <Loading />;
  if (!source.data) return <ErrorNotice error={source.error ?? new Error('未找到数据源')} />;

  const queryAvailable = source.data.status === 'CONNECTED' || source.data.status === 'SYNCED';
  const managedSpreadsheet = source.data.type === 'excel';

  return <section className="datasource-detail-page">
    <PageHeading
      title="Schema 与字段管理"
      description={managedSpreadsheet ? '已通过 Backend API 安全导入表格，可直接建立语义模型并进入问数。' : '同步数据源元数据，配置字段业务含义，管理 ChatBI 可用字段。'}
      actions={<>
        <Link className="button secondary" to={`/datasources/${id}/workspace`}>数据工作台</Link>
        <button className="button secondary" data-testid="sync-schema" disabled={sync.isPending} onClick={() => sync.mutate()}>{sync.isPending ? '正在刷新…' : '刷新数据'}</button>
        <label className="schema-select-label"><span className="sr-only">切换 Schema</span><select aria-label="切换 Schema" value={activeSchema} onChange={(event) => { setSelectedSchema(event.target.value); setSelected(''); }}>
          {(schemas.data ?? []).map((schema) => <option key={schema.name} value={schema.name}>{schema.name}</option>)}
        </select></label>
        <button className="button primary" onClick={openEdit}>编辑设置</button>
      </>}
    />

    {message && <div className="notice success" role="status">{message}</div>}
    <ErrorNotice error={source.error ?? schemas.error ?? allTables.error ?? tables.error ?? columns.error ?? test.error ?? sync.error ?? update.error} />

    <div className="schema-layout">
      <aside className="object-tree">
        <header><strong>数据库对象</strong><span>{allTables.data?.length ?? 0} 张表</span></header>
        <label className="tree-search"><span aria-hidden="true">⌕</span><input aria-label="搜索数据表" placeholder="搜索数据表" value={tableSearch} onChange={(event) => setTableSearch(event.target.value)} /></label>
        <div className="schema-tree-title"><strong>▾&nbsp;&nbsp;{activeSchema || 'Schema'}</strong><span>{allTables.data?.reduce((sum, table) => sum + (table.column_count ?? 0), 0) ?? 0}</span></div>
        <div className="table-tree-list">
          {filteredTables.map((table) => <button data-testid="schema-table" className={table.name === selected ? 'active' : ''} onClick={() => setSelected(table.name)} key={table.name}>
            <span>{table.name}</span><small>{table.column_count ?? ''}</small>
          </button>)}
          {!filteredTables.length && <p className="tree-empty">没有符合条件的数据表</p>}
        </div>
      </aside>

      <section className="column-panel">
        <header>
          <div><h2>{selected || '选择数据表'}</h2>{selected && <StatusBadge status="SYNCED" />}</div>
          <Link className="button small field-settings-link" to="/semantic-models">字段批量设置</Link>
        </header>
        <div className="column-table-wrap">
          <table data-testid="column-table">
            <thead><tr><th>字段 / 业务名称</th><th>类型</th><th>聚合角色</th><th>ChatBI</th></tr></thead>
            <tbody>{(columns.data ?? []).map((column) => <tr key={column.name}>
              <td><strong>{column.name}</strong><small>{column.comment || '尚未配置业务名称'}</small></td>
              <td>{column.type ?? column.data_type}</td>
              <td><span className="tag">{columnRole(column)}</span></td>
              <td><span className="badge badge-connected">可用</span></td>
            </tr>)}</tbody>
          </table>
          {!columns.isLoading && columns.data?.length === 0 && <div className="empty-inline">此表暂无字段元数据，请先刷新数据。</div>}
        </div>

        <section className="sample-preview" aria-label="样例数据预览">
          <header><strong>样例数据预览</strong><span>{sampleCount ? `仅显示前 ${sampleCount} 行 / 最多 5 行` : '未同步样例值'}</span></header>
          {sampleRows.length ? <div className="preview-scroll"><table><thead><tr>{previewColumns.map((column) => <th key={column.name}>{column.name}</th>)}</tr></thead><tbody>
            {sampleRows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((value, columnIndex) => <td key={previewColumns[columnIndex].name}>{displayValue(value)}</td>)}</tr>)}
          </tbody></table></div> : <div className="preview-empty">当前元数据未包含样例值，刷新数据后可查看。</div>}
        </section>
      </section>

      <aside className="table-info">
        <h2>表信息</h2>
        <label>物理表名<input value={selected} readOnly /></label>
        <label>表描述<textarea value={currentTable?.comment || '尚未配置表描述'} readOnly /></label>
        <label>主业务<input value="尚未配置" readOnly /></label>
        <label>表所有者<input value="尚未配置" readOnly /></label>
        <hr />
        <div className="metadata-switch-row"><div><strong>允许 ChatBI 查询</strong><small>由数据源只读权限控制</small></div><label className="metadata-switch"><input type="checkbox" checked={queryAvailable} disabled aria-label="允许 ChatBI 查询" /><span /></label></div>
        <hr />
        <h3>元数据同步</h3>
        <p>最近同步：{formatSyncTime(source.data.last_sync_at ?? source.data.last_synced_at)}</p>
        <p>Schema：{activeSchema || '--'}</p>
        <p>数据表：{source.data.table_count ?? tables.data?.length ?? 0}</p>
        <p>字段数量：{source.data.column_count ?? 0}</p>
        {managedSpreadsheet && <><hr /><h3>导入来源</h3><p>文件：{source.data.import_filename ?? '--'}</p><p>工作表：{source.data.import_sheet_count ?? 0}</p><p>总行数：{source.data.import_row_count ?? 0}</p></>}
      </aside>
    </div>

    {showEdit && <Modal title="编辑数据源设置" onClose={() => setShowEdit(false)}>
      <form className="form-grid" onSubmit={submitEdit}>
        <p className="form-intro">{managedSpreadsheet ? '表格运行连接由 Backend 托管，浏览器不可查看或修改；这里只允许修改显示名称。' : '修改连接配置后建议重新测试连接并刷新 Schema。密码留空表示保持现有密钥。'}</p>
        <Field label="数据源名称"><input required value={editForm.name} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} /></Field>
        {!managedSpreadsheet && <><div className="form-columns">
          <Field label="Host"><input required value={editForm.host} onChange={(event) => setEditForm({ ...editForm, host: event.target.value })} /></Field>
          <Field label="Port"><input required type="number" value={editForm.port} onChange={(event) => setEditForm({ ...editForm, port: Number(event.target.value) })} /></Field>
        </div>
        <Field label="Database"><input required value={editForm.database} onChange={(event) => setEditForm({ ...editForm, database: event.target.value })} /></Field>
        <div className="form-columns">
          <Field label="Username"><input required autoComplete="username" value={editForm.username} onChange={(event) => setEditForm({ ...editForm, username: event.target.value })} /></Field>
          <Field label="新密码（可选）"><input type="password" autoComplete="new-password" value={editForm.password} onChange={(event) => setEditForm({ ...editForm, password: event.target.value })} /></Field>
        </div>
        <Field label="默认 Schema"><input value={editForm.schema} onChange={(event) => setEditForm({ ...editForm, schema: event.target.value })} /></Field>
        <label className="check-row"><input type="checkbox" checked={editForm.ssl} onChange={(event) => setEditForm({ ...editForm, ssl: event.target.checked })} />启用 SSL 加密连接</label>
        <button className="button secondary test-connection-button" type="button" data-testid="test-connection" disabled={test.isPending} onClick={() => test.mutate()}>{test.isPending ? '测试中…' : '测试当前连接'}</button>
        </>}
        <ErrorNotice error={update.error ?? test.error} />
        <FormActions busy={update.isPending} onCancel={() => setShowEdit(false)} submitLabel="保存设置" />
      </form>
    </Modal>}
  </section>;
}
