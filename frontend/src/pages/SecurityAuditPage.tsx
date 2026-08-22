import { useEffect, useMemo, useState } from 'react';
import avatarCircle from '../assets/settings/avatar-circle.svg';
import timelineDot from '../assets/settings/timeline-dot.svg';
import { ApiError } from '../api/client';
import { securityApi } from '../api/security';
import type { SecurityOverview, SecurityUser } from '../types/api';
import './system-settings.css';

type SecurityTab = '用户' | '角色' | '权限策略';

const roleLabels = { ADMIN: '管理员', ANALYST: '数据分析师' } as const;

function UserAvatar({ name }: { name: string }) {
  return <span className="security-avatar"><img src={avatarCircle} alt="" /><b>{name.slice(0, 1)}</b></span>;
}

function formatTime(value?: string) {
  if (!value) return '尚无活动';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

export function SecurityAuditPage() {
  const [tab, setTab] = useState<SecurityTab>('用户');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('全部状态');
  const [overview, setOverview] = useState<SecurityOverview>();
  const [error, setError] = useState<unknown>();

  useEffect(() => {
    let active = true;
    securityApi.overview().then((value) => {
      if (active) setOverview(value);
    }).catch((reason) => {
      if (active) setError(reason);
    });
    return () => { active = false; };
  }, []);

  const filteredUsers = useMemo(() => (overview?.users ?? []).filter((user) => {
    const matchesQuery = `${user.display_name}${user.email}${user.role}`.toLowerCase().includes(query.trim().toLowerCase());
    const normalizedStatus = user.status === 'ACTIVE' ? '活跃' : '已停用';
    return matchesQuery && (status === '全部状态' || normalizedStatus === status);
  }), [overview?.users, query, status]);

  if (!overview && !error) {
    return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page"><header className="settings-page-heading"><div><h1>用户、角色与审计</h1><p>正在读取真实权限与审计记录…</p></div></header><div className="settings-provider-state" role="status">安全设置加载中…</div></div>;
  }

  if (!overview) {
    const denied = error instanceof ApiError && error.status === 403;
    return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page"><header className="settings-page-heading"><div><h1>用户、角色与审计</h1><p>管理工作空间成员、角色权限和关键操作审计记录。</p></div></header><div className="settings-provider-state" role="alert" data-testid={denied ? 'permission-denied' : 'security-error'}>{denied ? '权限不足：仅 ADMIN 可以查看系统权限与审计。' : `安全设置加载失败：${error instanceof Error ? error.message : '未知错误'}`}</div></div>;
  }

  const policyRows = overview.roles.flatMap((role) => role.permissions.map((permission) => ({ role: role.name, permission })));
  const currentRole = overview.roles.find((role) => role.name === 'ANALYST');

  return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page">
    <header className="settings-page-heading">
      <div><h1>用户、角色与审计</h1><p>管理工作空间成员、角色权限和关键操作审计记录。</p></div>
      <div className="settings-heading-actions"><button className="button secondary" type="button" disabled title="V1.3.0 不提供审计导出">导出审计</button><button className="button primary" type="button" disabled title="V1.3.0 仅提供最小 RBAC，不开放成员邀请">＋ 邀请成员</button></div>
    </header>

    <section className="security-kpis" aria-label="用户与审计指标">
      {[['人', '用户总数', overview.user_count], ['角', '角色数量', overview.role_count], ['活', '活跃用户', overview.active_user_count], ['审', '审计事件', overview.audit_event_count]].map(([icon, label, value]) => <article key={label}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong></article>)}
    </section>

    <section className="security-layout">
      <article className="security-table-card">
        <header className="security-table-tools">
          <div className="security-tabs" role="tablist" aria-label="安全管理视图">{(['用户', '角色', '权限策略'] as SecurityTab[]).map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{item}</button>)}</div>
          <div className="security-filters"><label><span className="sr-only">搜索成员</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索姓名、邮箱或角色" /></label><select aria-label="筛选状态" value={status} onChange={(event) => setStatus(event.target.value)}><option>全部状态</option><option>活跃</option><option>已停用</option></select></div>
        </header>

        <div className="security-table-scroll">
          {tab === '用户' && <table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>最后活跃</th><th>操作</th></tr></thead><tbody>{filteredUsers.length ? filteredUsers.map((user: SecurityUser) => <tr key={user.id}><td><div className="security-user-cell"><UserAvatar name={user.display_name} /><div><b>{user.display_name}</b><small>{user.email}</small></div></div></td><td>{roleLabels[user.role]}</td><td><span className={`security-state ${user.status === 'ACTIVE' ? 'active' : 'disabled'}`}>{user.status === 'ACTIVE' ? '活跃' : '已停用'}</span></td><td>{formatTime(user.last_active_at)}</td><td><button type="button" disabled>只读</button></td></tr>) : <tr><td className="security-empty-row" colSpan={5}>没有符合当前条件的成员</td></tr>}</tbody></table>}
          {tab === '角色' && <table><thead><tr><th>角色</th><th>成员数</th><th>权限数量</th><th>状态</th><th>操作</th></tr></thead><tbody>{overview.roles.map((role) => <tr key={role.name}><td><b>{roleLabels[role.name]}</b></td><td>{role.user_count} 人</td><td>{role.permissions.length} 项</td><td><span className="security-state active">启用</span></td><td><button type="button" disabled>系统角色</button></td></tr>)}</tbody></table>}
          {tab === '权限策略' && <table><thead><tr><th>权限</th><th>适用角色</th><th>资源范围</th><th>状态</th><th>操作</th></tr></thead><tbody>{policyRows.map((item) => <tr key={`${item.role}-${item.permission}`}><td><b>{item.permission}</b></td><td>{roleLabels[item.role]}</td><td>{item.permission.split('.')[0]}</td><td><span className="security-state active">已生效</span></td><td><button type="button" disabled>只读</button></td></tr>)}</tbody></table>}
        </div>
        <footer className="security-table-footer"><span>{tab === '用户' ? `共 ${overview.user_count} 位成员` : `${tab} · Backend API`}</span><div><button type="button" aria-label="上一页" disabled>‹</button><button type="button" className="active" aria-label="第 1 页" aria-current="page" disabled title="当前只有一页">1</button><button type="button" aria-label="下一页" disabled>›</button></div></footer>
      </article>

      <aside className="security-side-column">
        <article className="role-summary-card"><header><div><h2>角色权限摘要</h2><p>数据分析师</p></div><span>{currentRole?.user_count ?? 0} 人</span></header><div className="permission-grid"><div><small>问数据</small><strong className="allow">允许</strong></div><div><small>语义模型</small><strong>只读</strong></div><div><small>数据源</small><strong>授权范围</strong></div><div><small>系统设置</small><strong>拒绝</strong></div></div><button type="button" onClick={() => setTab('权限策略')}>查看完整权限矩阵</button></article>
        <article className="audit-events-card"><header><h2>最新审计事件</h2><span>{overview.audit_events.length} 条</span></header><div className="audit-timeline">{overview.audit_events.length ? overview.audit_events.slice(0, 4).map((event) => <div className="audit-event" key={event.id}><img src={timelineDot} alt="" /><div><b>{event.actor_email} · {event.action}</b><span>{formatTime(event.created_at)} · {event.resource_type} · {event.status}</span></div></div>) : <div className="security-empty-row">暂无审计事件</div>}</div></article>
      </aside>
    </section>
  </div>;
}
