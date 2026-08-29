import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import type { EChartsCoreOption } from 'echarts/core';
import { contentApi } from '../api/content';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import { EChart } from '../components/EChart';
import { ErrorNotice, Loading } from '../components/UI';
import { dashboardPresentation } from './dashboardPresentation';
import './dashboard-detail.css';

const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 });

function amount(value: number) {
  if (Math.abs(value) >= 100_000_000) return `¥${number.format(value / 100_000_000)}亿`;
  if (Math.abs(value) >= 10_000) return `¥${number.format(value / 10_000)}万`;
  return `¥${number.format(value)}`;
}

function saveJson(name: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function DashboardDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [notice, setNotice] = useState('');
  const [showAllRegions, setShowAllRegions] = useState(false);
  const result = useQuery({ queryKey: ['dashboard', id], queryFn: () => contentApi.dashboard(id), enabled: Boolean(id) });
  const data = result.data;
  const presentation = useMemo(() => dashboardPresentation(data?.dashboard ?? { name: '', description: '', trend_variant: 0 }), [data?.dashboard]);
  const revenueOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 420,
    color: [presentation.accent],
    grid: { left: 18, right: 20, top: 20, bottom: 18, containLabel: true },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: (value: unknown) => `${number.format(Number(value))} 万元` },
    xAxis: { type: 'category', boundaryGap: presentation.trendMode === 'bar', data: data?.revenue_trend.map((point) => point.date.slice(5)) ?? [], axisTick: { show: false }, axisLine: { lineStyle: { color: '#dfe5ef' } }, axisLabel: { color: '#75829a', fontSize: 10, margin: 11, hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { color: '#75829a', fontSize: 10 }, splitLine: { lineStyle: { color: '#e7ebf3' } }, axisLine: { show: false }, axisTick: { show: false } },
    series: [presentation.trendMode === 'bar' ? {
      type: 'bar', data: data?.revenue_trend.map((point) => Number((point.revenue / 10_000).toFixed(2))) ?? [], barMaxWidth: 32,
      itemStyle: { color: presentation.accent, borderRadius: [7, 7, 0, 0] },
    } : {
      type: 'line', smooth: presentation.trendMode === 'area', data: data?.revenue_trend.map((point) => Number((point.revenue / 10_000).toFixed(2))) ?? [], symbol: 'circle', symbolSize: 8,
      lineStyle: { width: 3, color: presentation.accent }, itemStyle: { color: '#fff', borderColor: presentation.accent, borderWidth: 3 },
      areaStyle: presentation.trendMode === 'area' ? { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${presentation.accent}40` }, { offset: 1, color: `${presentation.accent}05` }] } } : undefined,
    }],
  }), [data, presentation]);
  const regionOption = useMemo<EChartsCoreOption>(() => {
    const regions = data?.regions ?? [];
    const values = regions.map((row) => Number((row.revenue / 10_000).toFixed(2)));
    if (presentation.regionMode === 'donut' || presentation.regionMode === 'rose') return {
      animationDuration: 420,
      color: [presentation.accent, '#4f93ed', '#22b89a', '#f4a742', '#e76c8a', '#8b78e6'],
      tooltip: { trigger: 'item', confine: true, valueFormatter: (value: unknown) => `${number.format(Number(value))} 万元` },
      legend: { type: 'scroll', bottom: 0, left: 'center', itemWidth: 8, itemHeight: 8, textStyle: { color: '#75829a', fontSize: 9 } },
      series: [{
        type: 'pie', radius: presentation.regionMode === 'donut' ? ['42%', '68%'] : ['18%', '70%'], center: ['50%', '44%'],
        roseType: presentation.regionMode === 'rose' ? 'radius' : undefined,
        label: { show: true, color: '#526078', fontSize: 9, formatter: '{b}\n{d}%' }, labelLine: { length: 7, length2: 6 },
        data: regions.map((row, index) => ({ name: row.region, value: values[index] })),
      }],
    };
    const horizontal = presentation.regionMode === 'horizontal';
    const categoryAxis = { type: 'category' as const, data: regions.map((row) => row.region), axisTick: { show: false }, axisLine: { lineStyle: { color: '#dfe5ef' } }, axisLabel: { color: '#75829a', fontSize: 9, interval: 0 } };
    const valueAxis = { type: 'value' as const, show: false };
    return {
      animationDuration: 420,
      grid: { left: 12, right: 18, top: 10, bottom: 10, containLabel: true },
      tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'shadow' }, valueFormatter: (value: unknown) => `${number.format(Number(value))} 万元` },
      xAxis: horizontal ? valueAxis : categoryAxis,
      yAxis: horizontal ? { ...categoryAxis, inverse: true } : valueAxis,
      series: [{
        type: 'bar', data: values, barMaxWidth: horizontal ? 16 : 28,
        itemStyle: { color: presentation.accent, borderRadius: horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0] },
        label: { show: true, position: horizontal ? 'right' : 'top', color: '#526078', fontSize: 9, formatter: ({ value }: { value: unknown }) => number.format(Number(value)) },
      }],
    };
  }, [data, presentation]);
  const marginOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 420,
    color: [presentation.accent],
    grid: { left: 12, right: 18, top: 10, bottom: 10, containLabel: true },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: (value: unknown) => `${number.format(Number(value))}%` },
    xAxis: { type: 'category', data: data?.regions.map((row) => row.region) ?? [], axisTick: { show: false }, axisLine: { lineStyle: { color: '#dfe5ef' } }, axisLabel: { color: '#75829a', fontSize: 9, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#75829a', fontSize: 9, formatter: '{value}%' }, splitLine: { lineStyle: { color: '#eef1f6' } }, axisTick: { show: false }, axisLine: { show: false } },
    series: [presentation.marginMode === 'line' ? {
      type: 'line', smooth: true, data: data?.regions.map((row) => row.margin_percent) ?? [], symbolSize: 6, lineStyle: { width: 2.5, color: presentation.accent }, itemStyle: { color: presentation.accent },
    } : {
      type: 'bar', data: data?.regions.map((row) => row.margin_percent) ?? [], barMaxWidth: 22, itemStyle: { color: presentation.accent, borderRadius: [5, 5, 0, 0] },
    }],
  }), [data, presentation]);

  if (result.isLoading) return <Loading />;
  if (!data) return <ErrorNotice error={result.error ?? new Error('看板不存在')} />;
  const dataTime = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(`${data.data_as_of}T00:00:00`));
  async function refreshCard(cardId: string) {
    await contentApi.refreshDashboardCard(id, cardId);
    setNotice('卡片已从来源问题重新执行并刷新。');
    await result.refetch();
  }
  async function deleteCard(cardId: string) {
    await contentApi.deleteDashboardCard(id, cardId);
    setNotice('卡片已删除。');
    await result.refetch();
  }

  const regionalPrimary = presentation.kind === 'regional';

  return <div className={`dashboard-detail-page dashboard-${presentation.kind}`} data-dashboard-kind={presentation.kind} data-testid="dashboard-detail">
    <header className="detail-heading">
      <div><div className="detail-title-row"><h1>{data.dashboard.name}</h1><span className="dashboard-kind-badge">{presentation.label}</span><span className="live-state">实时数据正常</span></div></div>
      <div className="detail-actions">
        <button className="button secondary" type="button" onClick={() => document.documentElement.requestFullscreen?.()}>全屏</button>
        <button className="button secondary" type="button" onClick={() => saveJson(data.dashboard.name, data)}>导出</button>
        <button className="button soft" type="button" disabled title="看板编辑属于 P1，V1.3.0 不提供编辑能力">编辑看板</button>
        <button className="button primary" type="button" onClick={() => navigate('/answers')}>＋ 从已验证答案添加卡片</button>
      </div>
    </header>
    {notice && <div className="detail-notice" role="status">{notice}<button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}
    <section className="dashboard-filter-strip">
      <div><b>查询筛选</b><span>时间：{data.range_start} 至 {data.range_end}</span><span>区域：全部区域</span><span>部门：全部部门</span></div>
      <div><small>数据更新：{dataTime}</small><button type="button" onClick={() => result.refetch()} disabled={result.isFetching}>↻ {result.isFetching ? '刷新中' : '刷新'}</button></div>
    </section>
    <section className="detail-kpi-grid" aria-label="经营指标">
      {data.kpis.map((kpi) => <article key={kpi.label}><small>{kpi.label}</small><strong>{kpi.unit === '元' ? amount(kpi.value) : `${number.format(kpi.value)}${kpi.unit === '个' ? '' : kpi.unit}`}</strong><em className={kpi.change < 0 ? 'down' : ''}>{kpi.change >= 0 ? '↑' : '↓'} {number.format(Math.abs(kpi.change))}{kpi.change_unit}</em></article>)}
    </section>
    <section className={`detail-chart-grid dashboard-layout-${presentation.kind}`}>
      <article className="detail-card chart-card detail-primary-chart"><header><div><h2>{regionalPrimary ? presentation.regionTitle : presentation.trendTitle}</h2><p>{regionalPrimary ? `Top ${data.regions.length} 区域 · 单位：万元` : '按数据周期 · 单位：万元'}</p></div><span>总收入：{amount(data.kpis[0]?.value ?? 0)}</span></header><EChart option={regionalPrimary ? regionOption : revenueOption} label={regionalPrimary ? presentation.regionTitle : presentation.trendTitle} /></article>
      <div className="detail-chart-stack">
        <article className="detail-card chart-card detail-secondary-chart"><header><div><h2>{regionalPrimary ? presentation.trendTitle : presentation.regionTitle}</h2><p>{regionalPrimary ? '按数据周期' : `Top ${data.regions.length} 区域`}</p></div><small>{regionalPrimary ? '万元' : '收入构成'}</small></header><EChart option={regionalPrimary ? revenueOption : regionOption} label={regionalPrimary ? presentation.trendTitle : presentation.regionTitle} /></article>
        <article className="detail-card chart-card detail-secondary-chart"><header><div><h2>{presentation.marginTitle}</h2><p>区域经营质量</p></div><small>%</small></header><EChart option={marginOption} label={presentation.marginTitle} /></article>
      </div>
    </section>
    {(data.cards ?? []).length > 0 && <section className="verified-dashboard-cards" aria-label="已验证答案卡片"><header><div><h2>已验证答案卡片</h2><p>每张卡片都绑定来源 Query、结果签名与语义模型版本</p></div></header><div className="verified-card-grid">{(data.cards ?? []).map((card) => <article className="detail-card verified-card" key={card.id} data-testid="dashboard-answer-card"><header><div><h3>{card.title}</h3><p>来源问题：{card.source_question}</p></div><span>Semantic v{card.semantic_model_version}</span></header><EChartsRenderer spec={card.chart_spec} execution={card.result_snapshot} label={card.title} /><small>Query {card.query_run_id.slice(0, 8)} · Signature {card.result_signature?.slice(0, 12) ?? '—'}</small><footer><button type="button" onClick={() => navigate(`/ask/results?q=${encodeURIComponent(card.source_question)}&query_id=${encodeURIComponent(card.query_run_id)}`)}>查看来源问题</button><button type="button" onClick={() => refreshCard(card.id)}>刷新数据</button><button type="button" onClick={() => deleteCard(card.id)}>删除卡片</button></footer></article>)}</div></section>}
    <section className="detail-bottom-grid">
      <article className="detail-card region-table-card"><header><div><h2>重点区域经营表现</h2><p>按收入从高到低</p></div><button type="button" className="button small" aria-expanded={showAllRegions} onClick={() => setShowAllRegions((value) => !value)}>{showAllRegions ? '收起明细' : `查看全部 ${data.regions.length} 条`}</button></header><div className="detail-table-scroll"><table><thead><tr><th>区域</th><th>订单数</th><th>收入</th><th>充电量</th><th>利润率</th><th>环比</th></tr></thead><tbody>{(showAllRegions ? data.regions : data.regions.slice(0, 4)).map((row) => <tr key={row.region}><td><b>{row.region}区域营销中心</b></td><td>{number.format(row.order_count)}</td><td>{amount(row.revenue)}</td><td>{number.format(row.charging_kwh)} kWh</td><td>{number.format(row.margin_percent)}%</td><td className={row.change_percent < 0 ? 'negative' : 'positive'}>{row.change_percent >= 0 ? '+' : ''}{number.format(row.change_percent)}%</td></tr>)}</tbody></table></div></article>
      <article className="detail-card insight-card"><header><span>AI</span><h2>经营洞察</h2></header><p>{data.insight}</p><button type="button" onClick={() => navigate('/dashboards')}>基于该洞察返回看板列表</button></article>
    </section>
  </div>;
}
