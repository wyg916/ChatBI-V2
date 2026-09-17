import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { contentApi } from '../api/content';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import { ErrorNotice, Loading } from '../components/UI';
import './dashboard-detail.css';

export function DashboardDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const result = useQuery({ queryKey: ['dashboard-detail', id], queryFn: () => contentApi.dashboard(id) });
  const data = result.data;
  async function updateCard(cardId: string, remove = false) {
    setError(null);
    try {
      if (remove) await contentApi.deleteDashboardCard(id, cardId);
      else await contentApi.refreshDashboardCard(id, cardId);
      await result.refetch();
    } catch (cause) { setError(cause); }
  }
  if (result.isLoading) return <Loading />;
  if (!data) return <ErrorNotice error={result.error ?? new Error('看板不存在')} />;
  return <div className="dashboard-detail-page">
    <header className="detail-heading">
      <div><h1>{data.dashboard.name}</h1><p>来自已验证答案的查询结果</p></div>
      <button className="button primary" onClick={() => navigate('/answers')}>从答案库添加卡片</button>
    </header>
    {!!error && <ErrorNotice error={error} />}
    {data.cards.length === 0 && <p>尚未添加卡片。请先保存已验证答案，再添加到看板。</p>}
    <section className="verified-card-grid">
      {data.cards.map(card => <article className="detail-card verified-card" key={card.id}>
        <header><h2>{card.title}</h2><div>
          <button className="button secondary" onClick={() => updateCard(card.id)}>刷新</button>
          <button className="button secondary" onClick={() => updateCard(card.id, true)}>移除</button>
        </div></header>
        <p>{card.source_question}</p>
        <EChartsRenderer spec={card.chart_spec} execution={card.result_snapshot} />
      </article>)}
    </section>
  </div>;
}
