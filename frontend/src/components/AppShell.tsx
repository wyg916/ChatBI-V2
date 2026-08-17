import { NavLink, Outlet, useLocation } from 'react-router-dom';
import onlineIcon from '../assets/semantic/online.svg';
import { useAuth } from '../auth';

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

export function AppShell() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
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
      ? '数据已保存：刚刚'
    : pathname === '/semantic-models'
      ? '数据时效：近 24 小时'
      : isEvaluationDetail
        ? 'Golden Set · UI 演示'
      : isDatasourceDetail
        ? '数据源：连接状态⌄'
        : pathname === '/datasources'
          ? '数据引擎：本机分析引擎⌄'
          : isDashboardDetail
            ? '数据时效：业务数据最新日'
          : pathname === '/dashboards'
            ? '全部看板实时可用'
            : pathname === '/answers'
              ? '数据环境：正式发布版⌄'
              : isEvaluation
                ? '数据范围：近 30 天⌄'
                : pathname === '/settings/models'
                  ? '系统配置 · UI 演示'
                  : pathname === '/settings/security'
                    ? '权限策略 · UI 演示'
                    : '数据环境：正式分析库⌄';
  return (
    <div className={isAskRoute ? 'app-shell ask-shell' : 'app-shell'}>
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">BI</span><div><strong>ChatBI Studio</strong><small>AI NATIVE ANALYTICS</small></div></div>
        <div className="side-divider" />
        <div className="nav-caption">工作空间</div>
        <nav aria-label="一级导航">
          {navItems.map((item) => <NavLink key={item.to} to={item.to} end={'exact' in item && item.exact} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}><span>{item.icon}</span>{item.label}</NavLink>)}
        </nav>
        <div className="nav-caption manage">管理</div>
        <NavLink to="/settings/models" className={isSettings ? 'nav-item active' : 'nav-item'}><span>设</span>系统设置</NavLink>
        <div className="side-spacer" />
        <div className="user-card"><NavLink to="/settings/security"><span>{user.display_name.slice(0, 1)}</span><div><strong>{user.display_name}</strong><small>{user.role} · 当前工作空间</small></div></NavLink><button type="button" aria-label="退出登录" onClick={() => void logout()}>退出</button></div>
        <small className="version">v1.0.1 · 开源企业版</small>
      </aside>
      <div className="app-frame">
        <header className="topbar"><div><small>{headerCrumb}</small><h2>{title}</h2></div><div className="header-actions"><button className="context-pill"><img src={onlineIcon} alt="" />{contextLabel}</button><button className="icon-button" aria-label={isDashboardDetail ? '返回看板列表' : '帮助'} onClick={isDashboardDetail ? () => history.back() : undefined}>{isDashboardDetail ? '←' : '?'}</button>{(isContentLibrary || isDashboardDetail || isEvaluation || isSettings) && <button className="icon-button" aria-label="更多操作">{isDashboardDetail || isEvaluation ? '↑' : '⋯'}</button>}</div></header>
        <main className={isAskRoute ? 'page ask-page-canvas' : isContentLibrary ? 'page content-library-canvas' : isDashboardDetail ? 'page dashboard-detail-canvas' : isEvaluation ? 'page evaluation-canvas' : isEvaluationDetail ? 'page evaluation-detail-canvas' : 'page'}><Outlet /></main>
      </div>
    </div>
  );
}
