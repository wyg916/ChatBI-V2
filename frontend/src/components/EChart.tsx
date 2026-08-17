import { useEffect, useRef } from 'react';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { init, use, type EChartsCoreOption } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export function EChart({ option, label, className = '' }: { option: EChartsCoreOption; label: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || element.clientWidth === 0 || element.clientHeight === 0) return;
    const chart = init(element, undefined, { renderer: 'canvas' });
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [option]);
  return <div ref={ref} className={`data-echart ${className}`} role="img" aria-label={label} />;
}
