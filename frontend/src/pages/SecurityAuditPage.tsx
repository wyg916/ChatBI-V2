import { useDeferredValue, useEffect, useState } from 'react';
import avatarCircle from '../assets/settings/avatar-circle.svg';
import { API_BASE, ApiError } from '../api/client';
import { securityApi } from '../api/security';
import type {
  AuditPage, PermissionResource, ResourcePermission, SecurityOverview, SecurityUser,
  WorkspaceInvitation,
} from '../types/api';
import './system-settings.css';

type SecurityTab = '用户' | '角色' | '权限策略' | '邀请' | '审计日志';
const roleLabels = { ADMIN: '管理员', ANALYST: '数据分析师' } as const;
const resourceTypeLabels = {
  DATASOURCE: '数据源', SEMANTIC_MODEL: '语义模型', ANSWER: '答案', DASHBOARD: '看板',
} as const;
type PermissionDraft = Pick<ResourcePermission, 'can_read' | 'can_query'>;

function permissionKey(resource: PermissionResource) { return `${resource.resource_type}:${resource.resource_id}`; }

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
  const [memberOpen, setMemberOpen] = useState(false);
  const [member, setMember] = useState({ email: '', display_name: '', role: 'ANALYST', password: '' });
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState({ email: '', role: 'ANALYST', expires_in_days: 7 });
  const [inviteLink, setInviteLink] = useState('');
  const [permissionUserId, setPermissionUserId] = useState('');
  const [permissionDrafts, setPermissionDrafts] = useState<Record<string, PermissionDraft>>({});
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
  useEffect(() => {
    if (!overview?.users.length) { setPermissionUserId(''); return; }
    if (overview.users.some((user) => user.id === permissionUserId)) return;
    setPermissionUserId(overview.users.find((user) => user.role === 'ANALYST')?.id ?? overview.users[0].id);
  }, [overview, permissionUserId]);
  useEffect(() => {
    if (!overview || !permissionUserId) { setPermissionDrafts({}); return; }
    const grants = new Map<string, ResourcePermission>(
      (overview.resource_grants ?? [])
        .filter((grant) => grant.user_id === permissionUserId)
        .map((grant) => [`${grant.resource_type}:${grant.resource_id}`, grant] as const),
    );
    setPermissionDrafts(Object.fromEntries((overview.permission_resources ?? []).map((resource) => {
      const grant = grants.get(permissionKey(resource));
      return [permissionKey(resource), {
        can_read: grant?.can_read ?? false,
        can_query: grant?.can_query ?? false,
      }];
    })));
  }, [overview, permissionUserId]);

  async function mutate(action: () => Promise<unknown>, success: string) {
    setError(undefined); setNotice('');
    try { await action(); await refreshOverview(); setNotice(success); }
    catch (reason) { setError(reason); }
  }
  async function changeUser(user: SecurityUser, body: { role?: string; status?: string }) { await mutate(() => securityApi.updateUser(user.id, body), `${user.display_name} 已更新。`); }
  async function removeUser(user: SecurityUser) { if (confirm(`确认从工作空间移除 ${user.email}？`)) await mutate(() => securityApi.removeUser(user.id), `${user.display_name} 已移除。`); }
  function closeMember() { setMemberOpen(false); setMember({ email: '', display_name: '', role: 'ANALYST', password: '' }); }
  async function createMember() {
    setError(undefined); setNotice('');
    try {
      const value = await securityApi.createUser(member);
      closeMember();
      await refreshOverview();
      setNotice(`${value.display_name} 已加入当前工作空间，可使用所设邮箱和初始密码登录。`);
    } catch (reason) { setError(reason); }
  }
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

  function updatePermissionDraft(resource: PermissionResource, field: keyof PermissionDraft, checked: boolean) {
    setPermissionDrafts((current) => {
      const key = permissionKey(resource);
      const next = { ...(current[key] ?? { can_read: false, can_query: false }), [field]: checked };
      if (field === 'can_query' && checked) next.can_read = true;
      if (field === 'can_read' && !checked) next.can_query = false;
      return { ...current, [key]: next };
    });
  }

  async function saveResourcePermission(user: SecurityUser, resource: PermissionResource) {
    const draft = permissionDrafts[permissionKey(resource)] ?? { can_read: false, can_query: false };
    if (!draft.can_read && !draft.can_query) {
      setError(new Error('请至少启用读取权限；如需移除授权，请使用撤销。'));
      return;
    }
    await mutate(
      () => securityApi.setResourcePermission(user.id, resource.resource_type, resource.resource_id, draft),
      `${user.display_name} 的${resource.name}权限已保存。`,
    );
  }

  async function revokeResourcePermission(user: SecurityUser, resource: PermissionResource) {
    await mutate(
      () => securityApi.revokeResourcePermission(user.id, resource.resource_type, resource.resource_id),
      `${user.display_name} 的${resource.name}权限已撤销。`,
    );
  }

  if (!overview && !error) return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page"><header className="settings-page-heading"><div><h1>用户、角色与审计</h1><p>正在读取真实权限与审计记录…</p></div></header><div className="settings-provider-state" role="status">安全设置加载中…</div></div>;
  if (!overview) {
    const denied = error instanceof ApiError && error.status === 403;
    return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page"><header className="settings-page-heading"><div><h1>用户、角色与审计</h1></div></header><div className="settings-provider-state" role="alert" data-testid={denied ? 'permission-denied' : 'security-error'}>{denied ? '权限不足：仅 ADMIN 可以管理系统权限与审计。' : `安全设置加载失败：${error instanceof Error ? error.message : '未知错误'}`}</div></div>;
  }

  const policyRows = overview.roles.flatMap((role) => role.permissions.map((permission) => ({ role: role.name, permission })));
  const permissionUser = overview.users.find((user) => user.id === permissionUserId);
  const userGrants = new Map<string, ResourcePermission>(
    (overview.resource_grants ?? [])
      .filter((grant) => grant.user_id === permissionUserId)
      .map((grant) => [`${grant.resource_type}:${grant.resource_id}`, grant] as const),
  );
  return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page">
    <header className="settings-page-heading"><div><h1>用户、角色与审计</h1><p>所有变更由 Backend RBAC 强制并写入审计日志。</p></div><div className="settings-heading-actions"><button className="button secondary" type="button" onClick={() => void exportAudit()}>导出审计</button><button className="button secondary" type="button" onClick={() => setInviteOpen(true)}>邀请成员</button><button className="button primary" type="button" onClick={() => setMemberOpen(true)}>＋ 添加成员</button></div></header>
    {notice && <div className="settings-inline-notice" role="status">{notice}</div>}
    {Boolean(error) && <div className="settings-provider-state error" role="alert">{error instanceof Error ? error.message : '操作失败'}</div>}
    <section className="security-kpis" aria-label="用户与审计指标">{[['人', '用户总数', overview.user_count], ['角', '角色数量', overview.role_count], ['活', '活跃用户', overview.active_user_count], ['审', '审计事件', overview.audit_event_count]].map(([icon, label, value]) => <article key={label}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong></article>)}</section>
    <section className="security-table-card security-full-card">
      <header className="security-table-tools"><div className="security-tabs" role="tablist">{(['用户', '角色', '权限策略', '邀请', '审计日志'] as SecurityTab[]).map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => { setTab(item); setAuditPage(1); }}>{item}</button>)}</div><div className="security-filters"><input aria-label="搜索" value={query} onChange={(e) => { setQuery(e.target.value); setAuditPage(1); }} placeholder="搜索成员或审计" />{tab === '用户' && <select aria-label="筛选状态" value={status} onChange={(e) => setStatus(e.target.value)}><option value="ALL">全部状态</option><option value="ACTIVE">活跃</option><option value="DISABLED">已停用</option></select>}{tab === '审计日志' && <><input aria-label="审计开始时间" type="datetime-local" value={auditStart} onChange={(e) => { setAuditStart(e.target.value); setAuditPage(1); }} /><input aria-label="审计结束时间" type="datetime-local" value={auditEnd} onChange={(e) => { setAuditEnd(e.target.value); setAuditPage(1); }} /><input aria-label="操作者" value={auditActor} onChange={(e) => { setAuditActor(e.target.value); setAuditPage(1); }} placeholder="操作者" /><input aria-label="操作类型" value={auditAction} onChange={(e) => { setAuditAction(e.target.value); setAuditPage(1); }} placeholder="操作类型" /><input aria-label="资源类型" value={auditResource} onChange={(e) => { setAuditResource(e.target.value); setAuditPage(1); }} placeholder="资源类型" /><select aria-label="审计状态" value={auditStatus} onChange={(e) => { setAuditStatus(e.target.value); setAuditPage(1); }}><option value="">全部</option><option value="SUCCESS">SUCCESS</option><option value="FAILED">FAILED</option><option value="DENIED">DENIED</option></select></>}</div></header>
      <div className="security-table-scroll">
        {tab === '用户' && <table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>最后活跃</th><th>操作</th></tr></thead><tbody>{overview.users.map((user) => <tr key={user.id}><td><div className="security-user-cell"><UserAvatar name={user.display_name} /><div><b>{user.display_name}</b><small>{user.email}</small></div></div></td><td><select aria-label={`修改 ${user.display_name} 角色`} value={user.role} disabled={user.id === overview.current_actor?.id} title={user.id === overview.current_actor?.id ? '禁止管理员自我降权' : undefined} onChange={(e) => void changeUser(user, { role: e.target.value })}><option value="ADMIN">管理员</option><option value="ANALYST">数据分析师</option></select></td><td><span className={`security-state ${user.status === 'ACTIVE' ? 'active' : 'disabled'}`}>{user.status}</span></td><td>{formatTime(user.last_active_at)}</td><td><div className="security-row-actions"><button type="button" disabled={user.id === overview.current_actor?.id} title={user.id === overview.current_actor?.id ? '禁止管理员自我锁定' : undefined} onClick={() => void changeUser(user, { status: user.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE' })}>{user.status === 'ACTIVE' ? '停用' : '启用'}</button><button type="button" disabled={user.id === overview.current_actor?.id} onClick={() => void removeUser(user)}>移除</button></div></td></tr>)}</tbody></table>}
        {tab === '角色' && <table><thead><tr><th>角色</th><th>成员数</th><th>权限数</th><th>范围</th></tr></thead><tbody>{overview.roles.map((role) => <tr key={role.name}><td><b>{roleLabels[role.name]}</b></td><td>{role.user_count}</td><td>{role.permissions.length}</td><td>当前 Workspace</td></tr>)}</tbody></table>}
        {tab === '权限策略' && <div className="resource-permission-manager">
          <header className="resource-permission-heading">
            <div><h2>资源级权限</h2><p>按成员控制数据源、语义模型、答案和看板的读取、查询权限；所有修改实时写入 Backend RBAC 与审计日志。</p></div>
            <label>成员<select aria-label="选择权限成员" value={permissionUserId} onChange={(event) => setPermissionUserId(event.target.value)}>{overview.users.map((user) => <option key={user.id} value={user.id}>{user.display_name} · {roleLabels[user.role]}</option>)}</select></label>
          </header>
          {permissionUser?.role === 'ADMIN' ? <div className="admin-implicit-permission" role="status"><b>管理员为隐式全权</b><span>ADMIN 对当前 Workspace 的数据源、语义模型、答案和看板自动拥有读取与查询权限，无需也不能创建单独授权。</span></div> : <>
            <table aria-label="资源权限编辑器"><thead><tr><th>资源</th><th>类型</th><th>读取</th><th>查询</th><th>授权状态</th><th>操作</th></tr></thead><tbody>{(overview.permission_resources ?? []).length ? (overview.permission_resources ?? []).map((resource) => {
              const key = permissionKey(resource);
              const draft = permissionDrafts[key] ?? { can_read: false, can_query: false };
              const existing = userGrants.get(key);
              return <tr key={key}><td><b>{resource.name}</b><small>{resource.resource_id}</small></td><td>{resourceTypeLabels[resource.resource_type]}</td><td><label className="permission-check"><input aria-label={`读取 ${resource.name}`} type="checkbox" checked={draft.can_read} onChange={(event) => updatePermissionDraft(resource, 'can_read', event.target.checked)} /><span>允许</span></label></td><td><label className="permission-check"><input aria-label={`查询 ${resource.name}`} type="checkbox" checked={draft.can_query} onChange={(event) => updatePermissionDraft(resource, 'can_query', event.target.checked)} /><span>允许</span></label></td><td><span className={`security-state ${existing ? 'active' : 'disabled'}`}>{existing ? '已授权' : '未授权'}</span></td><td><div className="security-row-actions"><button type="button" aria-label={`保存 ${resource.name} 权限`} disabled={!draft.can_read && !draft.can_query} onClick={() => permissionUser && void saveResourcePermission(permissionUser, resource)}>保存</button><button type="button" aria-label={`撤销 ${resource.name} 权限`} disabled={!existing} onClick={() => permissionUser && void revokeResourcePermission(permissionUser, resource)}>撤销</button></div></td></tr>;
            }) : <tr><td colSpan={6} className="security-empty-row">当前工作空间暂无可授权的业务资源</td></tr>}</tbody></table>
          </>}
          <details className="role-policy-baseline"><summary>查看角色基础权限</summary><div>{policyRows.map((item) => <span key={`${item.role}-${item.permission}`}><b>{roleLabels[item.role]}</b>{item.permission}</span>)}</div></details>
        </div>}
        {tab === '邀请' && <table><thead><tr><th>邮箱</th><th>角色</th><th>状态</th><th>有效期</th><th>操作</th></tr></thead><tbody>{(overview.invitations ?? []).length ? (overview.invitations ?? []).map((item: WorkspaceInvitation) => <tr key={item.id}><td>{item.email}</td><td>{roleLabels[item.role]}</td><td>{item.status}</td><td>{formatTime(item.expires_at)}</td><td><button type="button" disabled={item.status !== 'PENDING'} title={item.status !== 'PENDING' ? `当前状态 ${item.status} 不可撤销` : undefined} onClick={() => void mutate(() => securityApi.revokeInvite(item.id), '邀请已撤销。')}>撤销</button></td></tr>) : <tr><td colSpan={5} className="security-empty-row">暂无邀请</td></tr>}</tbody></table>}
        {tab === '审计日志' && <table><thead><tr><th>时间 / 操作者</th><th>操作</th><th>资源</th><th>状态</th><th>详情</th></tr></thead><tbody>{(audit?.items ?? overview.audit_events).map((item) => <tr key={item.id}><td>{formatTime(item.created_at)}<small>{item.actor_email}</small></td><td>{item.action}</td><td>{item.resource_type}<small>{item.resource_id}</small></td><td>{item.status}</td><td><details><summary>查看</summary><pre>{JSON.stringify(item.details, null, 2)}</pre></details></td></tr>)}</tbody></table>}
      </div>
      <footer className="security-table-footer"><span>{tab === '审计日志' ? `共 ${audit?.total ?? overview.audit_event_count} 条 · 第 ${audit?.page ?? auditPage} 页` : '当前工作空间 · Backend RBAC'}</span>{tab === '审计日志' && <div><button type="button" disabled={auditPage <= 1} onClick={() => setAuditPage((value) => Math.max(1, value - 1))}>‹</button><button type="button" disabled={!audit || auditPage * audit.page_size >= audit.total} onClick={() => setAuditPage((value) => value + 1)}>›</button></div>}</footer>
    </section>
    {memberOpen && <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label="添加成员"><header><h2>添加成员</h2><button type="button" onClick={closeMember}>×</button></header><div className="form-grid"><p className="security-modal-intro">成员会立即加入当前工作空间；账号由 Backend 创建，密码只用于本次提交且不会回显。</p><label className="field">姓名<input autoComplete="off" value={member.display_name} onChange={(e) => setMember({ ...member, display_name: e.target.value })} placeholder="例如：运营分析师" /></label><label className="field">登录邮箱<input type="email" autoComplete="off" value={member.email} onChange={(e) => setMember({ ...member, email: e.target.value })} placeholder="name@example.com" /></label><label className="field">角色<select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value })}><option value="ANALYST">数据分析师</option><option value="ADMIN">管理员</option></select></label><label className="field">初始密码<input type="password" autoComplete="new-password" minLength={10} value={member.password} onChange={(e) => setMember({ ...member, password: e.target.value })} placeholder="至少 10 个字符" /></label><small className="security-password-hint">管理员拥有系统设置与审计管理权限；数据分析师仅拥有问数与业务资源读取权限。</small><div className="form-actions"><button className="button secondary" type="button" onClick={closeMember}>取消</button><button className="button primary" type="button" disabled={!member.display_name.trim() || !member.email.includes('@') || member.password.length < 10} onClick={() => void createMember()}>添加并启用</button></div></div></section></div>}
    {inviteOpen && <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label="邀请成员"><header><h2>邀请成员</h2><button type="button" onClick={() => setInviteOpen(false)}>×</button></header><div className="form-grid"><label className="field">邮箱<input type="email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></label><label className="field">Workspace<input value={overview.current_actor ? '当前工作空间' : ''} disabled title="邀请严格限定当前工作空间" /></label><label className="field">角色<select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="ANALYST">数据分析师</option><option value="ADMIN">管理员</option></select></label><label className="field">有效期（天）<input type="number" min={1} max={30} value={invite.expires_in_days} onChange={(e) => setInvite({ ...invite, expires_in_days: Number(e.target.value) })} /></label>{inviteLink && <label className="field">邀请链接<input readOnly value={inviteLink} /><button className="button secondary" type="button" onClick={() => void copyInvite(inviteLink)}>复制邀请链接</button></label>}<div className="form-actions"><button className="button secondary" type="button" onClick={() => setInviteOpen(false)}>关闭</button><button className="button primary" type="button" disabled={!invite.email.includes('@')} onClick={() => void createInvite()}>创建邀请</button></div></div></section></div>}
  </div>;
}
