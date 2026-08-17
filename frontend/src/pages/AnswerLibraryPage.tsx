import { useDeferredValue, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { contentApi } from '../api/content';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';
import type { AnswerStatus, VerifiedAnswer } from '../types/api';
import { ContentImportDialog, NewAnswerDialog } from './ContentDialogs';
import './content-library.css';

const number = new Intl.NumberFormat('zh-CN');
const statusLabel: Record<AnswerStatus, string> = { VERIFIED: '已验证', REJECTED: '已拒绝', DRAFT: '草稿', DEPRECATED: '已弃用' };

export function AnswerLibraryPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [tab, setTab] = useState('all');
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<'new' | 'import' | null>(null);
  const [selected, setSelected] = useState<VerifiedAnswer | null>(null);
  const [notice, setNotice] = useState('');
  const result = useQuery({
    queryKey: ['answers', deferredQuery, tab, page],
    queryFn: () => contentApi.answers({ query: deferredQuery, tab, page, pageSize: 6 }),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ['answers'] });
  const summary = result.data?.summary;
  const tabs = [
    ['all', '全部答案'],
    ['favorites', `已收藏 ${summary ? number.format(summary.favorites) : '—'}`],
    ['drafts', `草稿 ${summary ? number.format(summary.drafts) : '—'}`],
    ['verified', `已验证 ${summary ? number.format(summary.verified) : '—'}`],
  ];
  async function reuse(answer: VerifiedAnswer) {
    const queryResult = await contentApi.reuseAnswer(answer.id);
    navigate(`/ask/results?q=${encodeURIComponent(answer.question)}&query_id=${encodeURIComponent(queryResult.id)}`);
  }
  async function addToDashboard(answer: VerifiedAnswer) {
    const dashboards = await contentApi.dashboards({ pageSize: 1 });
    if (!dashboards.items.length) { setNotice('请先创建看板。'); return; }
    await contentApi.addDashboardCard(dashboards.items[0].id, answer.id);
    setNotice(`已添加到“${dashboards.items[0].name}”。`);
  }

  return <div className="content-library-page answer-library-page">
    <PageHeading title="答案库" description="沉淀和管理企业的标准问答、复用材料、规范 SQL 和数据口径，加速提升问答准确率。" actions={<>
      <button className="button secondary" type="button" onClick={() => setDialog('import')}>批量导入</button>
      <button className="button primary" type="button" onClick={() => setDialog('new')}>＋ 新建标准答案</button>
    </>} />
    <section className="content-summary" aria-label="答案库概览">
      <article><span>答</span><small>已收录答案</small><strong>{summary ? number.format(summary.total) : '—'}</strong></article>
      <article><span>准</span><small>平均推荐准确率</small><strong>{summary ? `${summary.average_accuracy.toFixed(1)}%` : '—'}</strong></article>
      <article><span>采</span><small>本月被采纳数</small><strong>{summary ? number.format(summary.monthly_adoptions) : '—'}</strong></article>
      <article><span>审</span><small>待审核</small><strong>{summary ? number.format(summary.pending_review) : '—'}</strong></article>
    </section>
    <section className="answer-table-card">
      {notice && <div className="content-notice" role="status">{notice}</div>}
      <header className="answer-table-tools">
        <div className="answer-tabs" role="tablist" aria-label="答案分类">
          {tabs.map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? 'active' : ''} type="button" onClick={() => { setTab(value); setPage(1); }}>{label}</button>)}
        </div>
        <div className="content-search-group">
          <label className="content-search"><span>⌕</span><input aria-label="搜索标准答案" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></label>
          <select aria-label="筛选答案状态" value={tab === 'review' ? 'review' : 'all'} onChange={(event) => { setTab(event.target.value === 'review' ? 'review' : 'all'); setPage(1); }}><option value="all">筛选</option><option value="review">待审核</option></select>
        </div>
      </header>
      <ErrorNotice error={result.error} />
      {result.isLoading ? <Loading /> : <div className="answer-table-scroll"><table className="answer-table">
        <thead><tr><th>标准问题</th><th>模型</th><th>责任人</th><th>状态</th><th>平均准确率</th><th>采纳数</th><th>操作</th></tr></thead>
        <tbody>{result.data?.items.map((answer) => <tr key={answer.id} data-testid="answer-row">
          <td><strong>{answer.question}</strong><small>{answer.module} · SQL {answer.sql_synced ? '已同步' : '待同步'}</small></td>
          <td>{answer.model_name}</td><td>{answer.owner_name}</td>
          <td><span className={`content-status status-${answer.status.toLowerCase()}`}>{statusLabel[answer.status]}</span></td>
          <td>{answer.accuracy_percent.toFixed(0)}%</td><td>{number.format(answer.adoption_count)}</td>
          <td><div className="answer-row-actions"><button className="content-link" type="button" onClick={() => setSelected(answer)}>查看</button><button className="content-link" type="button" disabled={answer.status !== 'VERIFIED'} onClick={() => reuse(answer)}>复用</button><button className="content-link" type="button" disabled={answer.status !== 'VERIFIED'} onClick={() => addToDashboard(answer)}>加入看板</button></div></td>
        </tr>)}</tbody>
      </table>{result.data?.items.length === 0 && <div className="content-empty">没有匹配的标准答案</div>}</div>}
      <footer className="content-pagination"><span>共 {number.format(result.data?.total ?? 0)} 条，当前显示 {result.data?.items.length ?? 0} 条</span><div><button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>‹</button><b>{page}</b><button type="button" aria-label="下一页" disabled={!result.data || page * result.data.page_size >= result.data.total} onClick={() => setPage((value) => value + 1)}>›</button></div></footer>
    </section>
    {selected && <section className="answer-detail-panel" aria-label="答案详情"><header><div><small>来源问题</small><h2>{selected.question}</h2></div><button type="button" aria-label="关闭答案详情" onClick={() => setSelected(null)}>×</button></header><div className="answer-detail-grid"><article><small>状态 / Oracle</small><strong>{statusLabel[selected.status]} / {selected.oracle_status ?? '未验证'}</strong></article><article><small>结果签名</small><strong>{selected.result_signature ?? '—'}</strong></article><article><small>语义模型版本</small><strong>v{selected.semantic_model_version ?? '—'}</strong></article></div><h3>业务结论</h3><p>{'conclusion' in selected.narrative ? String(selected.narrative.conclusion) : '草稿尚未生成可验证结论。'}</p><h3>查询依据</h3><pre><code>{selected.sql_text ?? '草稿尚未绑定 SQL。'}</code></pre><footer><button type="button" disabled={selected.status !== 'VERIFIED'} onClick={() => reuse(selected)}>复用问数</button><button type="button" disabled={selected.status !== 'VERIFIED'} onClick={() => addToDashboard(selected)}>保存为看板卡片</button></footer></section>}
    {dialog === 'new' && <NewAnswerDialog onClose={() => setDialog(null)} onSaved={refresh} />}
    {dialog === 'import' && <ContentImportDialog kind="answers" onClose={() => setDialog(null)} onSaved={refresh} />}
  </div>;
}
