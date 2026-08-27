import { useMemo } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { EChart } from '../components/EChart';
import type { ChartSpec, QueryExecution } from '../types/api';

function display(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  return value == null ? '—' : String(value);
}

export function buildControlledEChartsOption(spec: ChartSpec, execution: QueryExecution): EChartsCoreOption | null {
  const rows = (execution.rows ?? []).slice(0, spec.limit);
  const xField = spec.x_field;
  if (!rows.length || !spec.y_fields.length || spec.chart_type === 'KPI' || spec.chart_type === 'TABLE') return null;
  if (spec.chart_type === 'DONUT') {
    const metric = spec.y_fields[0];
    return {
      tooltip: { trigger: 'item', valueFormatter: (value: unknown) => `${display(value)}${spec.unit[metric] ?? ''}` }, legend: { top: 0, type: 'scroll' },
      series: [{ type: 'pie', radius: ['42%', '68%'], data: rows.map((row) => ({ name: display(xField ? row[xField] : ''), value: Number(row[metric] ?? 0) })) }],
    };
  }
  const categories = rows.map((row) => display(xField ? row[xField] : ''));
  const horizontal = spec.chart_type === 'HORIZONTAL_BAR';
  const categoryAxis = {
    type: 'category' as const,
    data: categories,
    axisLabel: { color: '#7c8aa5', width: horizontal ? 126 : 88, overflow: 'truncate' as const, interval: 0, rotate: !horizontal && rows.length > 8 ? 26 : 0 },
    axisPointer: { type: 'shadow' as const },
  };
  const valueAxis = { type: 'value' as const, axisLabel: { color: '#7c8aa5' }, splitLine: { lineStyle: { color: '#e8ecf4' } } };
  return {
    animationDuration: 350,
    grid: { left: horizontal ? 18 : 24, right: 30, top: 50, bottom: 58, containLabel: true },
    tooltip: { trigger: 'axis', confine: true },
    legend: { show: spec.legend.show !== false, top: 0, type: 'scroll' },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: spec.series.map((series) => ({
      name: series.name || spec.field_labels?.[series.field] || series.field,
      type: series.type === 'line' ? 'line' : 'bar',
      data: rows.map((row) => row[series.field] == null ? null : Number(row[series.field])),
      stack: series.stack,
      itemStyle: { color: series.type === 'line' ? '#5b5cf6' : undefined },
      lineStyle: { color: '#5b5cf6', width: 3 },
    })),
  };
}

export function EChartsRenderer({ spec, execution, label }: { spec: ChartSpec; execution: QueryExecution; label?: string }) {
  const option = useMemo(() => buildControlledEChartsOption(spec, execution), [spec, execution]);
  const rows = execution.rows ?? [];
  if (spec.chart_type === 'KPI') return <div className="controlled-kpi-chart" aria-label={label ?? spec.title}>{spec.y_fields.map((field) => <article key={field}><small>{spec.field_labels?.[field] || field}</small><strong>{display(rows[0]?.[field])}{spec.unit[field] ?? ''}</strong></article>)}</div>;
  if (spec.chart_type === 'TABLE' || !option) return <div className="controlled-table-chart" aria-label={label ?? spec.title}>完整结果见明细数据</div>;
  return <EChart option={option} label={label ?? spec.title} className="analysis-chart" />;
}
