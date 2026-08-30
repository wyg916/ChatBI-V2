import type { Dashboard } from '../types/api';

export type DashboardKind = 'executive' | 'regional' | 'customer' | 'supply' | 'marketing' | 'finance';

export interface DashboardPresentation {
  kind: DashboardKind;
  label: string;
  accent: string;
  accentSoft: string;
  trendMode: 'line' | 'area' | 'bar';
  regionMode: 'bar' | 'horizontal' | 'donut' | 'rose';
  marginMode: 'bar' | 'line';
  trendTitle: string;
  regionTitle: string;
  marginTitle: string;
}

const presentations: Record<DashboardKind, Omit<DashboardPresentation, 'kind'>> = {
  executive: {
    label: '经营总览', accent: '#5b5cf6', accentSoft: '#eeedff', trendMode: 'area', regionMode: 'bar', marginMode: 'line',
    trendTitle: '收入趋势', regionTitle: '区域收入排名', marginTitle: '区域利润率',
  },
  regional: {
    label: '区域经营', accent: '#2563eb', accentSoft: '#eaf2ff', trendMode: 'line', regionMode: 'horizontal', marginMode: 'bar',
    trendTitle: '区域业务收入趋势', regionTitle: '区域收入横向对比', marginTitle: '区域利润率对比',
  },
  customer: {
    label: '客户增长', accent: '#7c3aed', accentSoft: '#f2ebff', trendMode: 'area', regionMode: 'donut', marginMode: 'line',
    trendTitle: '收入趋势', regionTitle: '区域收入构成', marginTitle: '区域利润率',
  },
  supply: {
    label: '供应链运营', accent: '#0f9f7f', accentSoft: '#e8f8f4', trendMode: 'bar', regionMode: 'horizontal', marginMode: 'line',
    trendTitle: '收入趋势', regionTitle: '区域收入贡献', marginTitle: '区域利润率',
  },
  marketing: {
    label: '市场投放', accent: '#e86f2d', accentSoft: '#fff1e8', trendMode: 'line', regionMode: 'rose', marginMode: 'bar',
    trendTitle: '收入趋势', regionTitle: '区域收入构成', marginTitle: '区域利润率',
  },
  finance: {
    label: '财务分析', accent: '#1677b8', accentSoft: '#e8f5fc', trendMode: 'area', regionMode: 'donut', marginMode: 'bar',
    trendTitle: '收入趋势', regionTitle: '区域收入结构', marginTitle: '区域利润率对比',
  },
};

const fallbackKinds: DashboardKind[] = ['executive', 'regional', 'customer', 'supply', 'marketing', 'finance'];

function kindFromText(text: string): DashboardKind | undefined {
  if (/客户|用户|增长|留存|customer|growth/.test(text)) return 'customer';
  if (/区域|城市|门店|region|regional/.test(text)) return 'regional';
  if (/供应链|库存|采购|履约|supply|inventory/.test(text)) return 'supply';
  if (/市场|投放|渠道|营销|marketing|campaign/.test(text)) return 'marketing';
  if (/财务|现金|成本|利润|finance|financial/.test(text)) return 'finance';
  if (/经营|总览|管理|executive|overview/.test(text)) return 'executive';
  return undefined;
}

export function dashboardKind(dashboard: Pick<Dashboard, 'name' | 'description' | 'trend_variant'>): DashboardKind {
  const namedKind = kindFromText(dashboard.name.toLowerCase());
  if (namedKind) return namedKind;
  const describedKind = kindFromText(dashboard.description.toLowerCase());
  if (describedKind) return describedKind;
  const index = Math.abs(Number.isFinite(dashboard.trend_variant) ? dashboard.trend_variant : 0) % fallbackKinds.length;
  return fallbackKinds[index];
}

export function dashboardPresentation(dashboard: Pick<Dashboard, 'name' | 'description' | 'trend_variant'>): DashboardPresentation {
  const kind = dashboardKind(dashboard);
  return { kind, ...presentations[kind] };
}
