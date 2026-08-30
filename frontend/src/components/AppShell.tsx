import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import onlineIcon from '../assets/semantic/online.svg';
import { systemApi } from '../api/system';
import { useAuth } from '../auth';
import type { AppearanceSettings } from '../types/api';

const navItems = [
  { to: '/', label: '问数据', icon: '问', exact: true },
  { to: '/datasources', label: '数据源', icon: '源' },
  { to: '/semantic-models', label: '语义模型', icon: '模' },
  { to: '/answers', label: '答案库', icon: '答' },
  { to: '/dashboards', label: '看板', icon: '板' },
  { to: '/evaluation', label: '评测中心', icon: '测' },
] as const;

const titles: Record<string, [string, string]> = {
  '/': ['默认工作空间', '问数据'], '/ask/results': ['新能源经营分析工作空间', '问数据'],
  '/datasources': ['数据管理 / 数据源管理', '数据源'],
  '/semantic-models': ['语义层管理 / 语义模型', '语义模型'],
  '/answers': ['工作空间 / 智能问答', '答案库'], '/dashboards': ['看板列表 / 经营看板', '看板'],
  '/evaluation': ['评测与优化 / 评测中心', '评测中心'],
  '/settings/models': ['管理 / 系统设置', '系统设置'], '/settings/security': ['系统设置 / 用户角色与审计', '系统设置'],
};

export function parentRouteFor(pathname: string): { to: string; label: string } | undefined {
  const workspace = pathname.match(/^\/datasources\/([^/]+)\/workspace$/);
  if (workspace) return { to: `/datasources/${workspace[1]}`, label: '返回数据源详情' };
  if (/^\/datasources\/[^/]+$/.test(pathname)) return { to: '/datasources', label: '返回数据源列表' };
  if (/^\/semantic-models\/[^/]+$/.test(pathname)) return { to: '/semantic-models', label: '返回语义模型列表' };
  if (/^\/dashboards\/[^/]+$/.test(pathname)) return { to: '/dashboards', label: '返回看板列表' };
  if (/^\/evaluation\/[^/]+$/.test(pathname)) return { to: '/evaluation', label: '返回评测中心' };
  if (pathname === '/ask/results') return { to: '/', label: '返回问数据' };
  if (pathname === '/settings/security') return { to: '/settings/models', label: '返回系统设置' };
  return undefined;
}

export function AppShell() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const [appearance, setAppearance] = useState<AppearanceSettings>({ product_name: 'ChatBI Studio', brand_tagline: 'AI NATIVE ANALYTICS', logo_url: '', primary_color: '#5B5CF6', theme: 'LIGHT' });
  useEffect(() => {
    let active = true;
    systemApi.appearance().then((value) => { if (active) { setAppearance(value); document.documentElement.style.setProperty('--primary', value.primary_color); } }).catch(() => undefined);
    const update = (event: Event) => { const value = (event as CustomEvent<AppearanceSettings>).detail; if (value) setAppearance(value); };
    window.addEventListener('chatbi:appearance-updated', update);
    return () => { active = false; window.removeEventListener('chatbi:appearance-updated', update); };
  }, []);
  const key = Object.keys(titles).find((path) => path !== '/' && pathname.startsWith(path)) ?? '/';
  const [crumb, title] = titles[key];
  const isAskRoute = pathname === '/' || pathname.startsWith('/ask/');
  const isSemanticEditor = /^\/semantic-models\/[^/]+$/.test(pathname);
  const isContentLibrary = pathname === '/answers' || pathname === '/dashboards';
  const isDashboardDetail = /^\/dashboards\/[^/]+$/.test(pathname);
  const isEvaluation = pathname === '/evaluation';
  const datasourceId = pathname.match(/^\/datasources\/([^/]+)$/)?.[1] ?? '';
  const isDatasourceDetail = Boolean(datasourceId);
  const isEvaluationDetail = /^\/evaluation\/[^/]+$/.test(pathname);
  const isSettings = pathname.startsWith('/settings/');
  const parentRoute = parentRouteFor(pathname);
  const isAdmin = user.role === 'ADMIN';
  const headerCrumb = isSemanticEditor
    ? '语义模型 / 模型管理'
    : isDashboardDetail
      ? '看板 / 经营看板列表'
    : isDatasourceDetail
      ? '数据源 / Schema 管理'
      : isEvaluationDetail
        ? '评测中心 / 用例详情'
        : crumb;
  const contextLabel = isSemanticEditor
      ? '语义模型 · Backend API'
    : pathname === '/semantic-models'
      ? '语义模型 · Backend API'
      : isEvaluationDetail
        ? 'Golden Set · Backend API'
      : isDatasourceDetail
        ? '数据源 · Backend API'
        : pathname === '/datasources'
          ? '数据源 · Backend API'
          : isDashboardDetail
            ? '看板详情 · Backend API'
          : pathname === '/dashboards'
            ? '看板 · Backend API'
            : pathname === '/answers'
              ? '答案库 · Backend API'
              : isEvaluation
                ? '评测中心 · Backend API'
                : pathname === '/settings/models'
                  ? '系统配置 · Backend API'
                  : pathname === '/settings/security'
                    ? '权限策略 · Backend API'
                    : '问数据 · Backend API';
  return (
    <div className={isAskRoute ? 'app-shell ask-shell' : 'app-shell'}>
      <aside className="sidebar">
        <div className="brand">{appearance.logo_url ? <img className="brand-logo" style={{ width: 40, height: 40, objectFit: 'contain', borderRadius: 10 }} src={appearance.logo_url} alt="" /> : <span className="brand-mark">BI</span>}<div><strong>{appearance.product_name}</strong><small>{appearance.brand_tagline}</small></div></div>
        <div className="side-divider" />
        <div className="nav-caption">工作空间</div>
        <nav aria-label="一级导航">
          {navItems.map((item) => <NavLink key={item.to} to={item.to} end={'exact' in item && item.exact} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}><span>{item.icon}</span>{item.label}</NavLink>)}
        </nav>
        {isAdmin && <><div className="nav-caption manage">管理</div><NavLink to="/settings/models" className={isSettings ? 'nav-item active' : 'nav-item'}><span>设</span>系统设置</NavLink></>}
        <div className="side-spacer" />
        <div className="user-card">{isAdmin ? <NavLink to="/settings/security"><span>{user.display_name.slice(0, 1)}</span><div><strong>{user.display_name}</strong><small>{user.role} · 当前工作空间</small></div></NavLink> : <><span>{user.display_name.slice(0, 1)}</span><div><strong>{user.display_name}</strong><small>{user.role} · 当前工作空间</small></div></>}<button type="button" aria-label="退出登录" onClick={() => void logout()}>退出</button></div>
        <small className="version">v1.4.0 · 开源企业版</small>
      </aside>
      <div className="app-frame">
        <header className="topbar"><div><small>{headerCrumb}</small><h2>{title}</h2></div><div className="header-actions"><div className="context-pill" aria-label="当前页面上下文"><img src={onlineIcon} alt="" />{contextLabel}</div>{parentRoute ? <Link className="icon-button" aria-label={parentRoute.label} title={parentRoute.label} to={parentRoute.to}>←</Link> : <button className="icon-button" type="button" aria-label="帮助" disabled title="当前版本未提供独立帮助中心">?</button>}{(isContentLibrary || isDashboardDetail || isEvaluation || isSettings) && <button className="icon-button" type="button" aria-label="更多操作" disabled title="当前页面没有额外操作">{isDashboardDetail || isEvaluation ? '↑' : '⋯'}</button>}</div></header>
        <main className={isAskRoute ? 'page ask-page-canvas' : isContentLibrary ? 'page content-library-canvas' : isDashboardDetail ? 'page dashboard-detail-canvas' : isEvaluation ? 'page evaluation-canvas' : isEvaluationDetail ? 'page evaluation-detail-canvas' : 'page'}><Outlet /></main>
      </div>
    </div>
  );
}
