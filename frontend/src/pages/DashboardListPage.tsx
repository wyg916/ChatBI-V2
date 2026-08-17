import { useDeferredValue, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { contentApi } from '../api/content';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';
import { ContentImportDialog, NewDashboardDialog } from './ContentDialogs';
import trendArea0 from '../assets/dashboard-trends/trend-01.svg';
import trendLine0 from '../assets/dashboard-trends/trend-08.svg';
import trendArea1 from '../assets/dashboard-trends/trend-02.svg';
import trendLine1 from '../assets/dashboard-trends/trend-05.svg';
import trendArea2 from '../assets/dashboard-trends/trend-06.svg';
import trendLine2 from '../assets/dashboard-trends/trend-11.svg';
import trendArea3 from '../assets/dashboard-trends/trend-03.svg';
import trendLine3 from '../assets/dashboard-trends/trend-10.svg';
import trendArea4 from '../assets/dashboard-trends/trend-07.svg';
import trendLine4 from '../assets/dashboard-trends/trend-12.svg';
import trendArea5 from '../assets/dashboard-trends/trend-09.svg';
import trendLine5 from '../assets/dashboard-trends/trend-04.svg';
import './content-library.css';

const number = new Intl.NumberFormat('zh-CN');
const trends = [
  [trendArea0, trendLine0], [trendArea1, trendLine1], [trendArea2, trendLine2],
  [trendArea3, trendLine3], [trendArea4, trendLine4], [trendArea5, trendLine5],
];

function relativeUpdate(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 1) return '刚刚更新';
  if (minutes < 60) return `${minutes} 分钟前`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小时前`;
  if (minutes < 48 * 60) return '昨天';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value));
}

export function DashboardListPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [sort, setSort] = useState('recent');
  const [view, setView] = useState<'cards' | 'list'>('cards');
  const [dialog, setDialog] = useState<'new' | 'import' | null>(null);
  const result = useQuery({
    queryKey: ['dashboards', deferredQuery, sort],
    queryFn: () => contentApi.dashboards({ query: deferredQuery, sort, pageSize: 6 }),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ['dashboards'] });
  const summary = result.data?.summary;

  return <div className="content-library-page dashboard-list-page">
    <PageHeading title="看板" description="将可信问数结果沉淀为可共享、可刷新的经营分析页面。" actions={<>
      <button className="button secondary" type="button" onClick={() => setDialog('import')}>导入模板</button>
      <button className="button primary" type="button" onClick={() => setDialog('new')}>＋ 新建看板</button>
    </>} />
    <section className="content-summary" aria-label="看板概览">
      <article><span>板</span><small>看板总数</small><strong>{summary ? number.format(summary.total) : '—'}</strong></article>
      <article><span>卡</span><small>分析卡片</small><strong>{summary ? number.format(summary.cards) : '—'}</strong></article>
      <article><span>共</span><small>共享看板</small><strong>{summary ? number.format(summary.shared) : '—'}</strong></article>
      <article><span>刷</span><small>今日刷新</small><strong>{summary ? number.format(summary.refreshes_today) : '—'}</strong></article>
    </section>
    <section className="dashboard-tools" aria-label="看板筛选">
      <div className="dashboard-filter-group">
        <label className="content-search"><span>⌕</span><input aria-label="搜索看板" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <select aria-label="工作空间"><option>全部工作空间</option></select>
        <select aria-label="排序方式" value={sort} onChange={(event) => setSort(event.target.value)}><option value="recent">最近更新</option><option value="name">名称排序</option><option value="cards">卡片数量</option></select>
      </div>
      <div className="view-switch" aria-label="视图切换"><button type="button" className={view === 'cards' ? 'active' : ''} onClick={() => setView('cards')}>卡片视图</button><button type="button" className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>列表视图</button></div>
    </section>
    <ErrorNotice error={result.error} />
    {result.isLoading ? <Loading /> : <section className={`dashboard-grid dashboard-grid-${view}`}>
      {result.data?.items.map((dashboard) => {
        const [area, line] = trends[Math.abs(dashboard.trend_variant) % trends.length];
        return <Link className="dashboard-card" data-testid="dashboard-card" to={`/dashboards/${dashboard.id}`} key={dashboard.id}>
          <div className="dashboard-preview"><strong>{dashboard.name}</strong><span className="realtime-badge">实时</span><div className="dashboard-trend"><img src={area} alt="" /><img src={line} alt="" /></div></div>
          <div className="dashboard-card-title"><h2>{dashboard.name}</h2><b>{dashboard.card_count} 张卡片</b></div>
          <div className="dashboard-card-meta"><p>{dashboard.description}</p><time dateTime={dashboard.updated_at}>{relativeUpdate(dashboard.updated_at)}</time></div>
        </Link>;
      })}
      {result.data?.items.length === 0 && <div className="content-empty">没有匹配的看板</div>}
    </section>}
    {dialog === 'new' && <NewDashboardDialog onClose={() => setDialog(null)} onSaved={refresh} />}
    {dialog === 'import' && <ContentImportDialog kind="dashboards" onClose={() => setDialog(null)} onSaved={refresh} />}
  </div>;
}
