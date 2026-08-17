import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { evaluationApi } from '../api/evaluation';
import './evaluation.css';

function JsonTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  if (!rows.length) return <p>无结果行</p>;
  return <div className="evaluation-table-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 10).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{row[column] == null ? '—' : String(row[column])}</td>)}</tr>)}</tbody></table></div>;
}

export function EvaluationDetailPage() {
  const { id = '' } = useParams();
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ['evaluation-case', id], queryFn: () => evaluationApi.case(id), retry: false });
  const rerun = useMutation({
    mutationFn: evaluationApi.runGolden,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['evaluation-case', id] });
      await queryClient.invalidateQueries({ queryKey: ['evaluation-overview'] });
    },
  });
  const data = detail.data;
  const item = data?.case;
  const expected = (item?.expected.rows ?? []) as Array<Record<string, unknown>>;
  const actualPayload = item?.actual.execution as { rows?: Array<Record<string, unknown>>; result_signature?: string } | undefined;
  const actual = actualPayload?.rows ?? [];

  return <section className="evaluation-detail-page" data-testid="evaluation-case-detail">
    <header className="evaluation-page-heading">
      <div><p>评测中心 / Golden 20 / {item?.case_id ?? id}</p><h1>评测用例详情</h1></div>
      <div className="evaluation-heading-actions">
        {data?.previous_case_id ? <Link to={`/evaluation/${data.previous_case_id}`}>上一条</Link> : <button type="button" disabled>上一条</button>}
        {data?.next_case_id ? <Link to={`/evaluation/${data.next_case_id}`}>下一条</Link> : <button type="button" disabled>下一条</button>}
        <button type="button" className="primary" disabled={rerun.isPending} onClick={() => rerun.mutate()}>{rerun.isPending ? '运行中' : '重新运行'}</button>
      </div>
    </header>

    {detail.isLoading && <div className="evaluation-notice" role="status">正在读取持久化评测证据……</div>}
    {detail.isError && <div className="evaluation-notice" role="status">当前引用尚无持久化 Case 证据；请先在评测中心运行 Golden 20。</div>}
    {rerun.isError && <div className="evaluation-notice" role="status">评测运行失败：{(rerun.error as Error).message}</div>}

    {item && data && <div className="evaluation-layout">
      <div className="evaluation-main-column">
        <article className="evaluation-summary-card">
          <div className="evaluation-question-row"><div><span>标准问题</span><h2>{item.question}</h2></div><div className="evaluation-badges"><span className={item.status === 'PASS' ? 'success' : 'danger'}>{item.status}</span><span>{item.category}</span></div></div>
          <div className="evaluation-metric-grid">
            <article className={`evaluation-metric ${item.execution_ok ? 'success' : 'danger'}`}><span>SQL Execution</span><strong>{item.execution_ok ? 'PASS' : 'FAIL'}</strong></article>
            <article className={`evaluation-metric ${item.result_ok ? 'success' : 'danger'}`}><span>Result Value</span><strong>{item.result_ok ? 'PASS' : 'FAIL'}</strong></article>
            <article className={`evaluation-metric ${item.semantic_ok ? 'success' : 'danger'}`}><span>Semantic</span><strong>{item.semantic_ok ? 'PASS' : 'FAIL'}</strong></article>
            <article className="evaluation-metric"><span>Result Diff</span><strong>{item.result_diff.length}</strong></article>
          </div>
        </article>

        <div className="evaluation-sql-grid">
          <article className="evaluation-sql-card"><header><h2>Expected SQL</h2><span>冻结清单</span></header><pre className="evaluation-sql"><code>{String(item.expected.sql ?? '—')}</code></pre></article>
          <article className="evaluation-sql-card"><header><h2>Generated SQL</h2><span className={item.execution_ok ? 'success' : 'danger'}>{item.execution_ok ? '可执行' : '执行失败'}</span></header><pre className="evaluation-sql"><code>{item.generated_sql ?? 'SQL 未生成'}</code></pre></article>
        </div>

        <article className="evaluation-comparison-card"><header><div><h2>Expected</h2><p>冻结结果 · Signature {String(item.expected.result_signature ?? '—').slice(0, 16)}</p></div></header><JsonTable rows={expected} /></article>
        <article className="evaluation-comparison-card"><header><div><h2>Actual</h2><p>Query {item.query_run_id?.slice(0, 8) ?? '—'} · Signature {String(actualPayload?.result_signature ?? '—').slice(0, 16)}</p></div></header><JsonTable rows={actual} /></article>
      </div>

      <aside className="evaluation-side-column">
        <article className="evaluation-side-card error-card"><h2>错误分类</h2><strong>{item.error_category ?? '无错误'}</strong><p>{item.result_diff.length ? JSON.stringify(item.result_diff, null, 2) : 'Expected 与 Actual 通过 Result Oracle 校验。'}</p></article>
        <article className="evaluation-side-card semantics-card"><h2>业务语义</h2><dl><div><dt>指标</dt><dd>{String((item.expected.metrics as string[] | undefined)?.join('、') || '明细')}</dd></div><div><dt>维度</dt><dd>{String((item.expected.dimensions as string[] | undefined)?.join('、') || '无分组')}</dd></div><div><dt>过滤</dt><dd>{JSON.stringify(item.expected.filters ?? [])}</dd></div></dl></article>
        <article className="evaluation-side-card repair-card"><h2>证据链</h2><p>Run {data.run.id.slice(0, 8)}</p><p>Manifest {data.run.manifest_sha256?.slice(0, 16) ?? '—'}</p><p>Query {item.query_run_id?.slice(0, 8) ?? '—'}</p><Link to="/evaluation">返回评测中心</Link></article>
      </aside>
    </div>}
  </section>;
}
