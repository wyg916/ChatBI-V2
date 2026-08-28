import { describe, expect, it } from 'vitest';
import { buildControlledEChartsOption } from '../charting/EChartsRenderer';
import type { ChartSpec, QueryExecution } from '../types/api';

describe('buildControlledEChartsOption', () => {
  it('formats horizontal-bar metric values with separators and units while preserving long categories', () => {
    const longCustomerName = '华东新能源供应链综合服务有限公司超长客户名称';
    const spec: ChartSpec = {
      version: '1',
      chart_type: 'HORIZONTAL_BAR',
      title: '客户收入贡献排名',
      x_field: 'customer_name',
      y_fields: ['revenue'],
      series: [{ name: '收入', field: 'revenue', type: 'bar' }],
      aggregation: { revenue: 'SUM' },
      unit: { revenue: '元' },
      field_labels: { customer_name: '客户', revenue: '收入' },
      sort: ['-revenue'],
      limit: 15,
      legend: { show: true },
      axis: {},
      tooltip: {},
      data_source_query_id: 'query-1',
      result_signature: 'signature-1',
      bound_columns: ['customer_name', 'revenue'],
      bound_row_count: 1,
      null_policy: 'ZERO',
      warnings: [],
    };
    const execution: QueryExecution = {
      rows: [{ customer_name: longCustomerName, revenue: 12345 }],
    };

    const option = buildControlledEChartsOption(spec, execution) as {
      xAxis: { axisLabel: { formatter: (value: unknown) => string } };
      yAxis: { data: string[]; axisLabel: { overflow: string } };
      series: Array<{ tooltip: { valueFormatter: (value: unknown) => string } }>;
    };

    expect(option.xAxis.axisLabel.formatter(12345)).toBe('12,345元');
    expect(option.series[0].tooltip.valueFormatter(12345)).toBe('12,345元');
    expect(option.yAxis.data).toEqual([longCustomerName]);
    expect(option.yAxis.axisLabel.overflow).toBe('truncate');
  });
});
