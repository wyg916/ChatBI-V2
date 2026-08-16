import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { datasourceApi } from '../api/datasources';
import { useColumns, useDatasource, useTables } from '../hooks/useData';
import { ErrorNotice, Loading, PageHeading, StatusBadge } from '../components/UI';
import type { ColumnInfo } from '../types/api';

function constraint(column: ColumnInfo) {
  if (column.primary_key || column.is_primary_key) return <span className="tag">主键</span>;
  if (column.foreign_key || column.is_foreign_key) return <span className="tag">外键</span>;
  return column.nullable || column.is_nullable ? '可空' : '非空';
}

export function DatasourceDetailPage() {
  const { id = '' } = useParams();
  const client = useQueryClient();
  const source = useDatasource(id);
  const schema = source.data?.schema;
  const tables = useTables(id, schema);
  const [selected, setSelected] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => { if (!selected && tables.data?.[0]) setSelected(tables.data[0].name); }, [selected, tables.data]);
  const columns = useColumns(id, selected, schema);
  const test = useMutation({ mutationFn: () => datasourceApi.test(id), onSuccess: (data) => setMessage(data.message ?? (data.success ? '连接测试通过' : '连接测试失败')) });
  const sync = useMutation({ mutationFn: () => datasourceApi.sync(id), onSuccess: (data) => {
    client.invalidateQueries({ queryKey: ['tables', id, schema] });
    client.invalidateQueries({ queryKey: ['datasource', id] });
    setMessage(data.success === false ? 'Schema 同步未成功，请检查连接设置' : 'Schema 与字段元数据同步完成');
  }});
  if (source.isLoading || tables.isLoading) return <Loading />;
  return <>
    <PageHeading title="Schema 与字段管理" description={`同步 ${source.data?.name ?? '数据源'} 元数据，检查 ChatBI 可用字段。`} actions={<>
      <button className="button secondary" data-testid="test-connection" onClick={() => test.mutate()}>测试连接</button>
      <button className="button primary" data-testid="sync-schema" onClick={() => sync.mutate()}>↻ 刷新数据</button>
    </>} />
    {message && <div className="notice success">{message}</div>}
    <ErrorNotice error={source.error ?? tables.error ?? columns.error ?? test.error ?? sync.error}/>
    <div className="schema-layout">
      <aside className="object-tree">
        <header><strong>数据库对象</strong><span>{tables.data?.length ?? 0} 张表</span></header>
        <input placeholder="⌕  搜索数据表"/><h3>⌄ {source.data?.schema ?? 'public'}</h3>
        {tables.data?.map((table) => <button data-testid="schema-table" className={table.name === selected ? 'active' : ''} onClick={() => setSelected(table.name)} key={table.name}>{table.name}<small>{table.column_count ?? ''}</small></button>)}
      </aside>
      <section className="column-panel">
        <header><div><h2>{selected || '选择数据表'}</h2><StatusBadge status="CONNECTED" /></div><span>{columns.data?.length ?? 0} 个字段</span></header>
        <table data-testid="column-table"><thead><tr><th>字段 / 业务名称</th><th>类型</th><th>约束</th><th>ChatBI</th></tr></thead><tbody>
          {columns.data?.map((column) => <tr key={column.name}><td><strong>{column.name}</strong><small>{column.comment || '尚未配置业务名称'}</small></td><td>{column.type ?? column.data_type}</td><td>{constraint(column)}</td><td><span className="badge badge-connected">可用</span></td></tr>)}
        </tbody></table>
        {!columns.isLoading && columns.data?.length === 0 && <div className="empty-inline">此表暂无字段元数据，请先刷新数据。</div>}
      </section>
      <aside className="table-info">
        <h2>表信息</h2><label>物理表名<input value={selected} readOnly /></label><label>数据源<input value={source.data?.name ?? ''} readOnly /></label><label>数据库<input value={source.data?.database ?? ''} readOnly /></label>
        <hr/><h3>元数据同步</h3><p>最近同步：{source.data?.last_sync_at ?? source.data?.last_synced_at ?? '尚未同步'}</p><p>同步过程仅读取系统目录和少量样例值。</p>
      </aside>
    </div>
  </>;
}
