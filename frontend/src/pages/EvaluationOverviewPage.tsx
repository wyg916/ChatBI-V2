import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { EChartsCoreOption } from 'echarts/core';
import { evaluationApi } from '../api/evaluation';
import { EChart } from '../components/EChart';
import { ErrorNotice, Loading } from '../components/UI';
import './evaluation-overview.css';

const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 });
const icons = ['SQL', '值', '语', '时'];

function duration(value: number) {
  const minutes = Math.floor(value / 60).toString().padStart(2, '0');
  const seconds = Math.round(value % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

export function EvaluationOverviewPage() {
  const [notice, setNotice] = useState('');
  const result = useQuery({ queryKey: ['evaluation-overview'], queryFn: evaluationApi.overview });
  const data = result.data;
  const trendOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 420,
    grid: { left: 48, right: 18, top: 20, bottom: 34 },
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => `${number.format(Number(value))}%` },
    xAxis: { type: 'category', boundaryGap: false, data: data?.current.trend_points.map((point) => point.date) ?? [], axisTick: { show: false }, axisLine: { lineStyle: { color: '#dfe5ef' } }, axisLabel: { color: '#75829a', fontSize: 10, margin: 13 } },
    yAxis: { type: 'value', min: 86, max: 100, interval: 2, axisLabel: { color: '#75829a', fontSize: 10, formatter: '{value}%' }, splitLine: { lineStyle: { color: '#e7ebf3' } }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{ type: 'line', data: data?.current.trend_points.map((point) => point.value) ?? [], symbol: 'circle', symbolSize: 9, lineStyle: { width: 3, color: '#5b5cf6' }, itemStyle: { color: '#fff', borderColor: '#5b5cf6', borderWidth: 3 } }],
  }), [data]);
  const errorOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 420,
    tooltip: { trigger: 'item', formatter: '{b} {c}%' },
    legend: { orient: 'vertical', right: 6, top: 'middle', itemWidth: 10, itemHeight: 10, itemGap: 13, textStyle: { color: '#303b50', fontSize: 11 } },
    series: [{ type: 'pie', radius: ['48%', '70%'], center: ['28%', '52%'], avoidLabelOverlap: true, label: { show: true, position: 'center', formatter: `${data?.current.golden_set_count ?? 0}\n用例`, fontSize: 18, fontWeight: 700, color: '#172033', lineHeight: 26 }, labelLine: { show: false }, data: data?.current.error_distribution.map((item) => ({ name: `${item.label} ${item.percent}%`, value: item.percent, itemStyle: { color: item.color } })) ?? [] }],
  }), [data]);

  if (result.isLoading) return <Loading />;
  if (!data) return <ErrorNotice error={result.error ?? new Error('暂无评测记录')} />;
  const current = data.current;
  const completed = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(current.completed_at));
  const action = (label: string) => setNotice(`${label}入口已保留；当前页面只展示已完成的可复现评测记录，不伪造新的执行结果。`);

  return <div className="evaluation-page" data-testid="evaluation-overview">
    <header className="evaluation-heading"><div><h1>评测中心</h1><p>通过对比 SQL 生成率、结果集、语义理解、答案相关性等维度，全面评估模型。</p></div><div><button className="button secondary" type="button" onClick={() => action('导入评测集')}>导入评测集</button><button className="button secondary" type="button" onClick={() => action('新建评测任务')}>新建评测任务</button><button className="button primary" type="button" onClick={() => action('运行全部评测')}>▶ 运行全部评测</button></div></header>
    {notice && <div className="evaluation-notice" role="status">{notice}<button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}
    <section className="evaluation-kpis" aria-label="评测指标">
      {data.metrics.map((metric, index) => { const worse = metric.key === 'average_response_seconds' ? metric.change > 0 : metric.change < 0; return <article key={metric.key}><span>{icons[index]}</span><small>{metric.label}</small><strong>{number.format(metric.value)}{metric.unit}</strong><em className={worse ? 'worse' : ''}>{metric.change >= 0 ? '↑' : '↓'} {number.format(Math.abs(metric.change))}{metric.unit === 's' ? 's' : '%'}</em></article>; })}
    </section>
    <section className="evaluation-layout">
      <div className="evaluation-main-column">
        <div className="evaluation-chart-grid">
          <article className="evaluation-card evaluation-chart-card"><header><div><h2>近 30 天趋势图</h2><p>各项评测指标每日变化趋势</p></div><span>总体向好</span></header><EChart option={trendOption} label="近 30 天评测趋势" /></article>
          <article className="evaluation-card evaluation-chart-card"><header><div><h2>错误类型分布</h2><p>最近一次 Golden Set · {current.golden_set_count} 题</p></div></header><EChart option={errorOption} label="错误类型分布" /></article>
        </div>
        <article className="evaluation-card comparison-card"><header><div><h2>模型评测表现对比</h2><p>同一 Golden Set 评测结果集</p></div><button className="button small" type="button" onClick={() => action('查看全部评测')}>查看全部评测</button></header><div className="comparison-scroll"><table><thead><tr><th>模型</th><th>SQL 生成率</th><th>结果集准确率</th><th>语义理解准确率</th><th>平均响应时间</th><th>相关性准确率</th><th>结论</th></tr></thead><tbody>{data.comparisons.map((run, index) => <tr key={run.id}><td><b>{run.model_name}</b></td><td>{run.sql_generation_rate}%</td><td>{run.result_accuracy}%</td><td>{run.semantic_accuracy}%</td><td>{run.average_response_seconds}s</td><td>{run.relevance_accuracy}%</td><td><span className={`rank-badge rank-${index}`}>{index === 0 ? '当前最优' : index === 1 ? '次优' : '基准'}</span></td></tr>)}</tbody></table></div></article>
      </div>
      <aside className="current-model-panel"><small>当前评测模型</small><h2>{current.release_name}</h2><div className="release-state"><span>✓</span><div><b>全量发布</b><small>模型已通过全部评测点</small></div></div><hr/><dl><div><dt>Golden Set</dt><dd>{current.golden_set_count} / {current.golden_set_count}</dd></div><div><dt>SQL 生成率</dt><dd>{current.sql_generation_rate}%</dd></div><div><dt>结果集准确率</dt><dd>{current.result_accuracy}%</dd></div><div><dt>语义理解准确率</dt><dd>{current.semantic_accuracy}%</dd></div><div><dt>相关性准确率</dt><dd>{current.relevance_accuracy}%</dd></div><div><dt>平均响应时间</dt><dd className="plain">{current.average_response_seconds}s</dd></div></dl><button type="button" onClick={() => action('查看版本报告')}>查看版本报告</button><section><small>最近评测</small><b>{completed}</b><span>耗时 {duration(current.duration_seconds)}</span></section></aside>
    </section>
  </div>;
}
