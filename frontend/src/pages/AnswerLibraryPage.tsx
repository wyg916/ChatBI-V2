import { useDeferredValue, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { contentApi } from '../api/content';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';
import type { AnswerStatus } from '../types/api';
import { ContentImportDialog, NewAnswerDialog } from './ContentDialogs';
import './content-library.css';

const number = new Intl.NumberFormat('zh-CN');
const statusLabel: Record<AnswerStatus, string> = { PUBLISHED: '已发布', REVIEW: '审核', DRAFT: '草稿', ARCHIVED: '已归档' };

export function AnswerLibraryPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [tab, setTab] = useState('all');
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<'new' | 'import' | null>(null);
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
    ['published', `已发布 ${summary ? number.format(summary.published) : '—'}`],
  ];

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
          <td><Link className="content-link" to="/ask/results">查看</Link></td>
        </tr>)}</tbody>
      </table>{result.data?.items.length === 0 && <div className="content-empty">没有匹配的标准答案</div>}</div>}
      <footer className="content-pagination"><span>共 {number.format(result.data?.total ?? 0)} 条，当前显示 {result.data?.items.length ?? 0} 条</span><div><button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>‹</button><b>{page}</b><button type="button" aria-label="下一页" disabled={!result.data || page * result.data.page_size >= result.data.total} onClick={() => setPage((value) => value + 1)}>›</button></div></footer>
    </section>
    {dialog === 'new' && <NewAnswerDialog onClose={() => setDialog(null)} onSaved={refresh} />}
    {dialog === 'import' && <ContentImportDialog kind="answers" onClose={() => setDialog(null)} onSaved={refresh} />}
  </div>;
}
