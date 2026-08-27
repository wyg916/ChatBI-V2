import { useDeferredValue, useEffect, useState } from 'react';
import avatarCircle from '../assets/settings/avatar-circle.svg';
import { API_BASE, ApiError } from '../api/client';
import { securityApi } from '../api/security';
import type { AuditPage, SecurityOverview, SecurityUser, WorkspaceInvitation } from '../types/api';
import './system-settings.css';

type SecurityTab = '用户' | '角色' | '权限策略' | '邀请' | '审计日志';
const roleLabels = { ADMIN: '管理员', ANALYST: '数据分析师' } as const;

function UserAvatar({ name }: { name: string }) { return <span className="security-avatar"><img src={avatarCircle} alt="" /><b>{name.slice(0, 1)}</b></span>; }
function formatTime(value?: string) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '尚无活动'; }

export function SecurityAuditPage() {
  const initialAudit = new URLSearchParams(location.search).get('tab') === 'audit';
  const [tab, setTab] = useState<SecurityTab>(initialAudit ? '审计日志' : '用户');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('ALL');
  const [overview, setOverview] = useState<SecurityOverview>();
  const [audit, setAudit] = useState<AuditPage>();
  const [auditAction, setAuditAction] = useState('');
  const [auditStatus, setAuditStatus] = useState('');
  const [auditActor, setAuditActor] = useState('');
  const [auditResource, setAuditResource] = useState('');
  const [auditStart, setAuditStart] = useState('');
  const [auditEnd, setAuditEnd] = useState('');
  const [auditPage, setAuditPage] = useState(1);
  const [error, setError] = useState<unknown>();
  const [notice, setNotice] = useState('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState({ email: '', role: 'ANALYST', expires_in_days: 7 });
  const [inviteLink, setInviteLink] = useState('');
  const deferredQuery = useDeferredValue(query);

  async function refreshOverview() {
    const value = await securityApi.overview({ query: deferredQuery, status });
    setOverview(value);
  }
  useEffect(() => { setError(undefined); void refreshOverview().catch(setError); }, [deferredQuery, status]);
  useEffect(() => {
    if (tab !== '审计日志') return;
    void securityApi.audit({ query: deferredQuery, action: auditAction, actor: auditActor, resource: auditResource, event_status: auditStatus, start_at: auditStart ? new Date(auditStart).toISOString() : '', end_at: auditEnd ? new Date(auditEnd).toISOString() : '', page: auditPage, page_size: 25 }).then(setAudit).catch(setError);
  }, [tab, deferredQuery, auditAction, auditActor, auditResource, auditStatus, auditStart, auditEnd, auditPage]);

  async function mutate(action: () => Promise<unknown>, success: string) {
    setError(undefined); setNotice('');
    try { await action(); await refreshOverview(); setNotice(success); }
    catch (reason) { setError(reason); }
  }
  async function changeUser(user: SecurityUser, body: { role?: string; status?: string }) { await mutate(() => securityApi.updateUser(user.id, body), `${user.display_name} 已更新。`); }
  async function removeUser(user: SecurityUser) { if (confirm(`确认从工作空间移除 ${user.email}？`)) await mutate(() => securityApi.removeUser(user.id), `${user.display_name} 已移除。`); }
  async function createInvite() {
    try {
      const value = await securityApi.invite(invite);
      setInviteLink(value.invite_url ?? ''); setNotice('邀请已创建并持久化，可复制链接。');
      await refreshOverview();
    } catch (reason) { setError(reason); }
  }
  async function copyInvite(value: string) { try { await navigator.clipboard.writeText(value); setNotice('邀请链接已复制。'); } catch { setError(new Error('复制失败，请手动选择链接')); } }
  async function exportAudit() {
    try {
      const params = new URLSearchParams();
      Object.entries({ query: deferredQuery, action: auditAction, actor: auditActor, resource: auditResource, event_status: auditStatus, start_at: auditStart ? new Date(auditStart).toISOString() : '', end_at: auditEnd ? new Date(auditEnd).toISOString() : '' }).forEach(([key, value]) => { if (value) params.set(key, value); });
      const response = await fetch(`${API_BASE}/security/audit/export?${params.toString()}`, { credentials: 'include' });
      if (!response.ok) throw new Error(`导出失败 (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'chatbi-audit.csv'; anchor.click(); URL.revokeObjectURL(url);
      setNotice('审计日志已导出。');
    } catch (reason) { setError(reason); }
  }

  if (!overview && !error) return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page"><header className="settings-page-heading"><div><h1>用户、角色与审计</h1><p>正在读取真实权限与审计记录…</p></div></header><div className="settings-provider-state" role="status">安全设置加载中…</div></div>;
  if (!overview) {
    const denied = error instanceof ApiError && error.status === 403;
    return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page"><header className="settings-page-heading"><div><h1>用户、角色与审计</h1></div></header><div className="settings-provider-state" role="alert" data-testid={denied ? 'permission-denied' : 'security-error'}>{denied ? '权限不足：仅 ADMIN 可以管理系统权限与审计。' : `安全设置加载失败：${error instanceof Error ? error.message : '未知错误'}`}</div></div>;
  }

  const policyRows = overview.roles.flatMap((role) => role.permissions.map((permission) => ({ role: role.name, permission })));
  return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page">
    <header className="settings-page-heading"><div><h1>用户、角色与审计</h1><p>所有变更由 Backend RBAC 强制并写入审计日志。</p></div><div className="settings-heading-actions"><button className="button secondary" type="button" onClick={() => void exportAudit()}>导出审计</button><button className="button primary" type="button" onClick={() => setInviteOpen(true)}>＋ 邀请成员</button></div></header>
    {notice && <div className="settings-inline-notice" role="status">{notice}</div>}
    {Boolean(error) && <div className="settings-provider-state error" role="alert">{error instanceof Error ? error.message : '操作失败'}</div>}
    <section className="security-kpis" aria-label="用户与审计指标">{[['人', '用户总数', overview.user_count], ['角', '角色数量', overview.role_count], ['活', '活跃用户', overview.active_user_count], ['审', '审计事件', overview.audit_event_count]].map(([icon, label, value]) => <article key={label}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong></article>)}</section>
    <section className="security-table-card security-full-card">
      <header className="security-table-tools"><div className="security-tabs" role="tablist">{(['用户', '角色', '权限策略', '邀请', '审计日志'] as SecurityTab[]).map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => { setTab(item); setAuditPage(1); }}>{item}</button>)}</div><div className="security-filters"><input aria-label="搜索" value={query} onChange={(e) => { setQuery(e.target.value); setAuditPage(1); }} placeholder="搜索成员或审计" />{tab === '用户' && <select aria-label="筛选状态" value={status} onChange={(e) => setStatus(e.target.value)}><option value="ALL">全部状态</option><option value="ACTIVE">活跃</option><option value="DISABLED">已停用</option></select>}{tab === '审计日志' && <><input aria-label="审计开始时间" type="datetime-local" value={auditStart} onChange={(e) => { setAuditStart(e.target.value); setAuditPage(1); }} /><input aria-label="审计结束时间" type="datetime-local" value={auditEnd} onChange={(e) => { setAuditEnd(e.target.value); setAuditPage(1); }} /><input aria-label="操作者" value={auditActor} onChange={(e) => { setAuditActor(e.target.value); setAuditPage(1); }} placeholder="操作者" /><input aria-label="操作类型" value={auditAction} onChange={(e) => { setAuditAction(e.target.value); setAuditPage(1); }} placeholder="操作类型" /><input aria-label="资源类型" value={auditResource} onChange={(e) => { setAuditResource(e.target.value); setAuditPage(1); }} placeholder="资源类型" /><select aria-label="审计状态" value={auditStatus} onChange={(e) => { setAuditStatus(e.target.value); setAuditPage(1); }}><option value="">全部</option><option value="SUCCESS">SUCCESS</option><option value="FAILED">FAILED</option><option value="DENIED">DENIED</option></select></>}</div></header>
      <div className="security-table-scroll">
        {tab === '用户' && <table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>最后活跃</th><th>操作</th></tr></thead><tbody>{overview.users.map((user) => <tr key={user.id}><td><div className="security-user-cell"><UserAvatar name={user.display_name} /><div><b>{user.display_name}</b><small>{user.email}</small></div></div></td><td><select aria-label={`修改 ${user.display_name} 角色`} value={user.role} disabled={user.id === overview.current_actor?.id} title={user.id === overview.current_actor?.id ? '禁止管理员自我降权' : undefined} onChange={(e) => void changeUser(user, { role: e.target.value })}><option value="ADMIN">管理员</option><option value="ANALYST">数据分析师</option></select></td><td><span className={`security-state ${user.status === 'ACTIVE' ? 'active' : 'disabled'}`}>{user.status}</span></td><td>{formatTime(user.last_active_at)}</td><td><div className="security-row-actions"><button type="button" disabled={user.id === overview.current_actor?.id} title={user.id === overview.current_actor?.id ? '禁止管理员自我锁定' : undefined} onClick={() => void changeUser(user, { status: user.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE' })}>{user.status === 'ACTIVE' ? '停用' : '启用'}</button><button type="button" disabled={user.id === overview.current_actor?.id} onClick={() => void removeUser(user)}>移除</button></div></td></tr>)}</tbody></table>}
        {tab === '角色' && <table><thead><tr><th>角色</th><th>成员数</th><th>权限数</th><th>范围</th></tr></thead><tbody>{overview.roles.map((role) => <tr key={role.name}><td><b>{roleLabels[role.name]}</b></td><td>{role.user_count}</td><td>{role.permissions.length}</td><td>当前 Workspace</td></tr>)}</tbody></table>}
        {tab === '权限策略' && <table><thead><tr><th>权限</th><th>适用角色</th><th>资源范围</th><th>状态</th></tr></thead><tbody>{policyRows.map((item) => <tr key={`${item.role}-${item.permission}`}><td><b>{item.permission}</b></td><td>{roleLabels[item.role]}</td><td>{item.permission.split('.')[0]}</td><td><span className="security-state active">后端生效</span></td></tr>)}</tbody></table>}
        {tab === '邀请' && <table><thead><tr><th>邮箱</th><th>角色</th><th>状态</th><th>有效期</th><th>操作</th></tr></thead><tbody>{(overview.invitations ?? []).length ? (overview.invitations ?? []).map((item: WorkspaceInvitation) => <tr key={item.id}><td>{item.email}</td><td>{roleLabels[item.role]}</td><td>{item.status}</td><td>{formatTime(item.expires_at)}</td><td><button type="button" disabled={item.status !== 'PENDING'} title={item.status !== 'PENDING' ? `当前状态 ${item.status} 不可撤销` : undefined} onClick={() => void mutate(() => securityApi.revokeInvite(item.id), '邀请已撤销。')}>撤销</button></td></tr>) : <tr><td colSpan={5} className="security-empty-row">暂无邀请</td></tr>}</tbody></table>}
        {tab === '审计日志' && <table><thead><tr><th>时间 / 操作者</th><th>操作</th><th>资源</th><th>状态</th><th>详情</th></tr></thead><tbody>{(audit?.items ?? overview.audit_events).map((item) => <tr key={item.id}><td>{formatTime(item.created_at)}<small>{item.actor_email}</small></td><td>{item.action}</td><td>{item.resource_type}<small>{item.resource_id}</small></td><td>{item.status}</td><td><details><summary>查看</summary><pre>{JSON.stringify(item.details, null, 2)}</pre></details></td></tr>)}</tbody></table>}
      </div>
      <footer className="security-table-footer"><span>{tab === '审计日志' ? `共 ${audit?.total ?? overview.audit_event_count} 条 · 第 ${audit?.page ?? auditPage} 页` : '当前工作空间 · Backend RBAC'}</span>{tab === '审计日志' && <div><button type="button" disabled={auditPage <= 1} onClick={() => setAuditPage((value) => Math.max(1, value - 1))}>‹</button><button type="button" disabled={!audit || auditPage * audit.page_size >= audit.total} onClick={() => setAuditPage((value) => value + 1)}>›</button></div>}</footer>
    </section>
    {inviteOpen && <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label="邀请成员"><header><h2>邀请成员</h2><button type="button" onClick={() => setInviteOpen(false)}>×</button></header><div className="form-grid"><label className="field">邮箱<input type="email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></label><label className="field">Workspace<input value={overview.current_actor ? '当前工作空间' : ''} disabled title="邀请严格限定当前工作空间" /></label><label className="field">角色<select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="ANALYST">数据分析师</option><option value="ADMIN">管理员</option></select></label><label className="field">有效期（天）<input type="number" min={1} max={30} value={invite.expires_in_days} onChange={(e) => setInvite({ ...invite, expires_in_days: Number(e.target.value) })} /></label>{inviteLink && <label className="field">邀请链接<input readOnly value={inviteLink} /><button className="button secondary" type="button" onClick={() => void copyInvite(inviteLink)}>复制邀请链接</button></label>}<div className="form-actions"><button className="button secondary" type="button" onClick={() => setInviteOpen(false)}>关闭</button><button className="button primary" type="button" disabled={!invite.email.includes('@')} onClick={() => void createInvite()}>创建邀请</button></div></div></section></div>}
  </div>;
}
