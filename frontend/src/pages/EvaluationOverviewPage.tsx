import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
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
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState('');
  const result = useQuery({ queryKey: ['evaluation-overview'], queryFn: evaluationApi.overview });
  const runGolden = useMutation({
    mutationFn: evaluationApi.runGolden,
    onSuccess: async (value) => {
      setNotice(`Golden ${value.run.golden_set_count} 执行完成：${value.run.status}。`);
      await queryClient.invalidateQueries({ queryKey: ['evaluation-overview'] });
    },
    onError: (error: Error) => setNotice(`评测运行失败：${error.message}`),
  });
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
  const action = (label: string) => setNotice(`${label}不在 Day 3 Golden 20 主链路内，本轮未伪造该写操作。`);

  return <div className="evaluation-page" data-testid="evaluation-overview">
    <header className="evaluation-heading"><div><h1>评测中心</h1><p>执行冻结 Golden 20，保存 SQL、结果值、语义匹配和 Result Diff 证据。</p></div><div><button className="button secondary" type="button" onClick={() => action('导入评测集')}>导入评测集</button><button className="button secondary" type="button" onClick={() => action('新建评测任务')}>新建评测任务</button><button className="button primary" type="button" disabled={runGolden.isPending} onClick={() => runGolden.mutate()}>▶ {runGolden.isPending ? '正在执行 Golden 20' : '运行 Golden 20'}</button></div></header>
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
        <article className="evaluation-card comparison-card"><header><div><h2>最近评测运行</h2><p>每次运行均保存真实 Case Detail 与 Result Diff</p></div><Link className="button small" to="/evaluation/G01">查看 Case Detail</Link></header><div className="comparison-scroll"><table><thead><tr><th>运行</th><th>SQL 执行成功</th><th>结果值准确</th><th>语义匹配</th><th>危险 SQL 阻断</th><th>平均响应时间</th><th>结论</th></tr></thead><tbody>{data.comparisons.map((run) => <tr key={run.id}><td><b>{run.release_name}</b></td><td>{run.sql_execution_pass_count}/{run.golden_set_count}</td><td>{run.result_value_pass_count}/{run.golden_set_count}</td><td>{run.semantic_pass_count}/{run.golden_set_count}</td><td>{run.dangerous_sql_block_count}/{run.dangerous_sql_total}</td><td>{run.average_response_seconds}s</td><td><span className={`rank-badge ${run.status === 'PASS' ? 'rank-0' : 'rank-2'}`}>{run.status}</span></td></tr>)}</tbody></table></div></article>
      </div>
      <aside className="current-model-panel"><small>当前评测运行</small><h2>{current.release_name}</h2><div className="release-state"><span>{current.status === 'PASS' ? '✓' : '!'}</span><div><b>{current.status}</b><small>由持久化评测记录计算</small></div></div><hr/><dl><div><dt>Golden Set</dt><dd>{current.golden_set_count}</dd></div><div><dt>SQL 执行成功</dt><dd>{current.sql_execution_pass_count} / {current.golden_set_count}</dd></div><div><dt>结果值准确</dt><dd>{current.result_value_pass_count} / {current.golden_set_count}</dd></div><div><dt>语义匹配</dt><dd>{current.semantic_pass_count} / {current.golden_set_count}</dd></div><div><dt>危险 SQL 阻断</dt><dd>{current.dangerous_sql_block_count} / {current.dangerous_sql_total}</dd></div><div><dt>平均响应时间</dt><dd className="plain">{current.average_response_seconds}s</dd></div></dl><Link to="/evaluation/G01">查看 Case Detail</Link><section><small>最近评测</small><b>{completed}</b><span>耗时 {duration(current.duration_seconds)}</span></section></aside>
    </section>
  </div>;
}
