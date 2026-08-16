import { NavLink, Outlet, useLocation } from 'react-router-dom';

const navItems = [
  { to: '/', label: '问数据', icon: '问', exact: true },
  { to: '/datasources', label: '数据源', icon: '源' },
  { to: '/semantic-models', label: '语义模型', icon: '模' },
  { to: '/answers', label: '答案库', icon: '答' },
  { to: '/dashboards', label: '看板', icon: '板' },
  { to: '/evaluation', label: '评测中心', icon: '测' },
] as const;

const titles: Record<string, [string, string]> = {
  '/': ['默认工作空间', '问数据'], '/ask/results': ['默认工作空间', '问数据'],
  '/datasources': ['数据管理 / 数据源管理', '数据源'],
  '/semantic-models': ['语义层管理 / 语义模型', '语义模型'],
  '/answers': ['知识沉淀 / 已验证答案', '答案库'], '/dashboards': ['数据洞察 / 经营看板', '看板'],
  '/evaluation': ['质量中心 / 自动评测', '评测中心'],
  '/settings/models': ['系统管理 / 模型服务', '系统设置'], '/settings/security': ['系统管理 / 安全与审计', '用户角色与审计'],
};

export function AppShell() {
  const { pathname } = useLocation();
  const key = Object.keys(titles).find((path) => path !== '/' && pathname.startsWith(path)) ?? '/';
  const [crumb, title] = titles[key];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">BI</span><div><strong>ChatBI Studio</strong><small>AI NATIVE ANALYTICS</small></div></div>
        <div className="side-divider" />
        <div className="nav-caption">工作空间</div>
        <nav aria-label="一级导航">
          {navItems.map((item) => <NavLink key={item.to} to={item.to} end={'exact' in item && item.exact} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}><span>{item.icon}</span>{item.label}</NavLink>)}
        </nav>
        <div className="nav-caption manage">管理</div>
        <NavLink to="/settings/models" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}><span>设</span>系统设置</NavLink>
        <div className="side-spacer" />
        <NavLink to="/settings/security" className="user-card"><span>王</span><div><strong>王迎港</strong><small>管理员 · 数据分析部</small></div></NavLink>
        <small className="version">v2.0.0 · 开源企业版</small>
      </aside>
      <div className="app-frame">
        <header className="topbar"><div><small>{crumb}</small><h2>{title}</h2></div><div className="header-actions"><button className="context-pill"><i />数据环境：开发分析库⌄</button><button className="icon-button" aria-label="帮助">?</button></div></header>
        <main className="page"><Outlet /></main>
      </div>
    </div>
  );
}
