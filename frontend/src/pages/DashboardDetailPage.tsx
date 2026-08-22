import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import type { EChartsCoreOption } from 'echarts/core';
import { contentApi } from '../api/content';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import { EChart } from '../components/EChart';
import { ErrorNotice, Loading } from '../components/UI';
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
  const revenueOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 420,
    grid: { left: 54, right: 20, top: 24, bottom: 34 },
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => `${number.format(Number(value))} 万元` },
    xAxis: { type: 'category', boundaryGap: false, data: data?.revenue_trend.map((point) => point.date.slice(5)) ?? [], axisTick: { show: false }, axisLine: { lineStyle: { color: '#dfe5ef' } }, axisLabel: { color: '#75829a', fontSize: 10, margin: 13 } },
    yAxis: { type: 'value', axisLabel: { color: '#75829a', fontSize: 10 }, splitLine: { lineStyle: { color: '#e7ebf3' } }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{ type: 'line', data: data?.revenue_trend.map((point) => Number((point.revenue / 10_000).toFixed(2))) ?? [], symbol: 'circle', symbolSize: 9, lineStyle: { width: 3, color: '#5b5cf6' }, itemStyle: { color: '#fff', borderColor: '#5b5cf6', borderWidth: 3 } }],
  }), [data]);
  const regionOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 420,
    grid: { left: 18, right: 18, top: 34, bottom: 34 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value: unknown) => `${number.format(Number(value))} 万元` },
    xAxis: { type: 'category', data: data?.regions.map((row) => row.region) ?? [], axisTick: { show: false }, axisLine: { lineStyle: { color: '#dfe5ef' } }, axisLabel: { color: '#75829a', fontSize: 10, margin: 13 } },
    yAxis: { type: 'value', show: false },
    series: [{ type: 'bar', data: data?.regions.map((row) => Number((row.revenue / 10_000).toFixed(2))) ?? [], barWidth: '58%', itemStyle: { color: '#5b5cf6', borderRadius: [7, 7, 0, 0] }, label: { show: true, position: 'top', color: '#465268', fontSize: 10, formatter: ({ value }: { value: unknown }) => number.format(Number(value)) } }],
  }), [data]);

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

  return <div className="dashboard-detail-page" data-testid="dashboard-detail">
    <header className="detail-heading">
      <div><div className="detail-title-row"><h1>{data.dashboard.name}</h1><span className="live-state">实时数据正常</span></div></div>
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
    <section className="detail-chart-grid">
      <article className="detail-card chart-card"><header><div><h2>收入趋势图表</h2><p>单位：万元</p></div><span>总收入：{amount(data.kpis[0]?.value ?? 0)}</span></header><EChart option={revenueOption} label="收入趋势图表" /></article>
      <article className="detail-card chart-card"><header><div><h2>分区域收入图表</h2><p>Top {data.regions.length} 区域</p></div><small>万元</small></header><EChart option={regionOption} label="分区域收入图表" /></article>
    </section>
    {(data.cards ?? []).length > 0 && <section className="verified-dashboard-cards" aria-label="已验证答案卡片"><header><div><h2>已验证答案卡片</h2><p>每张卡片都绑定来源 Query、结果签名与语义模型版本</p></div></header><div className="verified-card-grid">{(data.cards ?? []).map((card) => <article className="detail-card verified-card" key={card.id} data-testid="dashboard-answer-card"><header><div><h3>{card.title}</h3><p>来源问题：{card.source_question}</p></div><span>Semantic v{card.semantic_model_version}</span></header><EChartsRenderer spec={card.chart_spec} execution={card.result_snapshot} label={card.title} /><small>Query {card.query_run_id.slice(0, 8)} · Signature {card.result_signature?.slice(0, 12) ?? '—'}</small><footer><button type="button" onClick={() => navigate(`/ask/results?q=${encodeURIComponent(card.source_question)}&query_id=${encodeURIComponent(card.query_run_id)}`)}>查看来源问题</button><button type="button" onClick={() => refreshCard(card.id)}>刷新数据</button><button type="button" onClick={() => deleteCard(card.id)}>删除卡片</button></footer></article>)}</div></section>}
    <section className="detail-bottom-grid">
      <article className="detail-card region-table-card"><header><div><h2>重点区域经营表现</h2><p>按收入从高到低</p></div><button type="button" className="button small" aria-expanded={showAllRegions} onClick={() => setShowAllRegions((value) => !value)}>{showAllRegions ? '收起明细' : `查看全部 ${data.regions.length} 条`}</button></header><div className="detail-table-scroll"><table><thead><tr><th>区域</th><th>订单数</th><th>收入</th><th>充电量</th><th>利润率</th><th>环比</th></tr></thead><tbody>{(showAllRegions ? data.regions : data.regions.slice(0, 4)).map((row) => <tr key={row.region}><td><b>{row.region}区域营销中心</b></td><td>{number.format(row.order_count)}</td><td>{amount(row.revenue)}</td><td>{number.format(row.charging_kwh)} kWh</td><td>{number.format(row.margin_percent)}%</td><td className={row.change_percent < 0 ? 'negative' : 'positive'}>{row.change_percent >= 0 ? '+' : ''}{number.format(row.change_percent)}%</td></tr>)}</tbody></table></div></article>
      <article className="detail-card insight-card"><header><span>AI</span><h2>经营洞察</h2></header><p>{data.insight}</p><button type="button" onClick={() => navigate('/dashboards')}>基于该洞察返回看板列表</button></article>
    </section>
  </div>;
}
