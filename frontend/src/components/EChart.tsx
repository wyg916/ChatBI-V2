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
    if (!element) return;
    let chart: ReturnType<typeof init> | undefined;
    const resize = () => {
      const width = Math.floor(element.getBoundingClientRect().width || element.clientWidth);
      const height = Math.floor(element.getBoundingClientRect().height || element.clientHeight);
      if (width <= 0 || height <= 0) return;
      if (!chart) {
        chart = init(element, undefined, { renderer: 'canvas', width, height });
        chart.setOption(option);
      } else {
        chart.resize({ width, height, silent: true });
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    window.addEventListener('resize', resize);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', resize);
      chart?.dispose();
    };
  }, [option]);
  return <div ref={ref} className={`data-echart ${className}`} role="img" aria-label={label} />;
}
