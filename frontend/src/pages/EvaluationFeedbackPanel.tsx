import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { evaluationApi } from '../api/evaluation';
import { ErrorNotice, Loading } from '../components/UI';


export function EvaluationFeedbackPanel() {
  const queryClient = useQueryClient();
  const result = useQuery({ queryKey: ['evaluation-feedback-dashboard'], queryFn: evaluationApi.feedbackDashboard });
  const [notice, setNotice] = useState('');
  const [queryRunId, setQueryRunId] = useState('');
  const [comment, setComment] = useState('业务口径需要人工修正');
  const [correctedSql, setCorrectedSql] = useState('');
  const [expectedRows, setExpectedRows] = useState('[]');
  const [recallQuestion, setRecallQuestion] = useState('');

  const refresh = async () => queryClient.invalidateQueries({ queryKey: ['evaluation-feedback-dashboard'] });
  const correct = useMutation({
    mutationFn: () => evaluationApi.correct(queryRunId, comment),
    onSuccess: () => setNotice('回答正确反馈已记录。'),
    onError: (error: Error) => setNotice(`正确反馈失败：${error.message}`),
  });
  const incorrect = useMutation({
    mutationFn: async () => {
      const rows = JSON.parse(expectedRows) as Array<Record<string, unknown>>;
      const columns = rows[0] ? Object.keys(rows[0]) : [];
      return evaluationApi.incorrect({
        query_run_id: queryRunId,
        comment,
        corrected_sql: correctedSql,
        expected_columns: columns,
        expected_rows: rows,
        owner_name: '当前用户',
      });
    },
    onSuccess: async (workflow) => {
      setNotice(`人工修正已提交：${workflow.workflow_state}。`);
      await refresh();
    },
    onError: (error: Error) => setNotice(`人工修正失败：${error.message}`),
  });
  const review = useMutation({
    mutationFn: ({ answerId, decision }: { answerId: string; decision: 'APPROVE' | 'REJECT' }) =>
      evaluationApi.review(answerId, decision, decision === 'APPROVE' ? 'Oracle 与业务口径复核通过' : '业务口径复核不通过'),
    onSuccess: async (workflow) => {
      setNotice(`审核完成：${workflow.workflow_state}，版本 ${workflow.version}。`);
      await refresh();
    },
    onError: (error: Error) => setNotice(`审核失败：${error.message}`),
  });
  const recall = useMutation({
    mutationFn: () => evaluationApi.recall(recallQuestion),
    onError: (error: Error) => setNotice(`召回失败：${error.message}`),
  });
  const replay = useMutation({
    mutationFn: (answerId: string) => evaluationApi.replay(answerId, recallQuestion),
    onSuccess: async (value) => {
      setNotice(`安全回放 ${value.replay_passed ? 'PASS' : 'FAIL'}：Guard ${value.guard_status} / Oracle ${value.oracle_status} / Replay ${(value.replay_rate * 100).toFixed(0)}%。`);
      await refresh();
    },
    onError: (error: Error) => setNotice(`安全回放失败：${error.message}`),
  });

  if (result.isLoading) return <Loading />;
  if (!result.data) return <ErrorNotice error={result.error ?? new Error('反馈数据不可用')} />;
  const data = result.data;
  const candidates = recall.data?.candidates ?? [];

  return <div className="evaluation-page feedback-page" data-testid="feedback-page">
    <header className="evaluation-heading">
      <div><h1>反馈与 Verified SQL</h1><p>错误反馈、人工修正、审核、相似召回与安全回放全部保留版本和 Oracle 证据。</p></div>
      <Link className="button secondary" to="/evaluation">返回评测 Dashboard</Link>
    </header>
    {notice && <div className="evaluation-notice" role="status">{notice}<button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}

    <section className="feedback-kpis" aria-label="反馈闭环指标">
      <article><small>术语库</small><strong>{data.terminology.length}</strong></article>
      <article><small>Verified SQL</small><strong>{data.sql_examples.length}</strong></article>
      <article><small>回放通过</small><strong>{data.passed_replays}/{data.total_replays}</strong></article>
      <article><small>FEEDBACK_REPLAY_RATE</small><strong>{(data.feedback_replay_rate * 100).toFixed(0)}%</strong></article>
    </section>

    <section className="feedback-grid">
      <article className="evaluation-card feedback-form-card">
        <header><div><h2>提交用户反馈与人工修正</h2><p>修正 SQL 会重新进入正式 SQL Guard、只读执行和 Result Oracle。</p></div></header>
        <label>Query Run ID<input value={queryRunId} onChange={(event) => setQueryRunId(event.target.value)} placeholder="查询运行 ID" /></label>
        <label>反馈说明<textarea value={comment} onChange={(event) => setComment(event.target.value)} /></label>
        <div className="feedback-actions"><button className="button secondary" type="button" disabled={!queryRunId || correct.isPending} onClick={() => correct.mutate()}>回答正确</button></div>
        <label>人工修正 SQL<textarea className="sql-input" value={correctedSql} onChange={(event) => setCorrectedSql(event.target.value)} placeholder="单条 SELECT / WITH SELECT" /></label>
        <label>期望结果 JSON<textarea className="sql-input" value={expectedRows} onChange={(event) => setExpectedRows(event.target.value)} /></label>
        <button className="button primary" type="button" disabled={!queryRunId || !correctedSql || incorrect.isPending} onClick={() => incorrect.mutate()}>提交错误反馈与修正</button>
      </article>

      <article className="evaluation-card feedback-form-card">
        <header><div><h2>相似问题召回与回放</h2><p>只召回已审核、Oracle PASS 的 Verified SQL 候选。</p></div></header>
        <label>相似问题<input value={recallQuestion} onChange={(event) => setRecallQuestion(event.target.value)} placeholder="再次提出相似问题" /></label>
        <button className="button primary" type="button" disabled={!recallQuestion || recall.isPending} onClick={() => recall.mutate()}>召回候选</button>
        <div className="feedback-candidates" data-testid="verified-sql-candidates">
          {candidates.map((item) => <div key={item.answer_id}><div><b>{item.question}</b><small>相似度 {(item.score * 100).toFixed(1)}% · v{item.version}</small></div><button className="button small" type="button" disabled={replay.isPending} onClick={() => replay.mutate(item.answer_id)}>正式安全回放</button></div>)}
          {recall.isSuccess && candidates.length === 0 && <p>没有通过审核的相似 Verified SQL。</p>}
        </div>
      </article>
    </section>

    <section className="evaluation-card feedback-workflows" data-testid="feedback-workflows">
      <header><div><h2>修正审核与版本记录</h2><p>Verified SQL 晋升必须同时满足人工审核和 Oracle PASS。</p></div></header>
      <div className="comparison-scroll"><table><thead><tr><th>问题</th><th>状态</th><th>Oracle</th><th>版本</th><th>操作</th></tr></thead><tbody>
        {data.workflows.map((item) => <tr key={item.answer_id}><td><b>{item.question}</b><small>{item.workflow_state}</small></td><td>{item.status}</td><td>{item.oracle_status ?? 'NOT_RUN'}</td><td>v{item.version}</td><td>{item.status === 'DRAFT' ? <div className="feedback-actions"><button className="button small" type="button" onClick={() => review.mutate({ answerId: item.answer_id, decision: 'APPROVE' })}>审核通过</button><button className="button small secondary" type="button" onClick={() => review.mutate({ answerId: item.answer_id, decision: 'REJECT' })}>拒绝</button></div> : '已处理'}</td></tr>)}
        {data.workflows.length === 0 && <tr><td colSpan={5}>暂无修正工作流</td></tr>}
      </tbody></table></div>
    </section>

    <section className="feedback-grid compact">
      <article className="evaluation-card feedback-list"><header><div><h2>术语库</h2><p>来自已发布语义模型</p></div></header>{data.terminology.slice(0, 12).map((item) => <div key={`${item.term}-${item.mapped_object}`}><b>{item.term}</b><span>{item.synonyms.join('、')}</span><small>{item.definition}</small></div>)}</article>
      <article className="evaluation-card feedback-list"><header><div><h2>SQL 示例</h2><p>仅展示 Verified / Oracle PASS</p></div></header>{data.sql_examples.slice(0, 12).map((item) => <div key={item.answer_id}><b>{item.question}</b><code>{item.sql}</code><small>v{item.version}</small></div>)}</article>
    </section>
  </div>;
}
