import { FormEvent, useMemo, useState } from 'react';
import avatarCircle from '../assets/settings/avatar-circle.svg';
import timelineDot from '../assets/settings/timeline-dot.svg';
import { Field, FormActions, Modal } from '../components/UI';
import './system-settings.css';

type SecurityTab = '用户' | '角色' | '权限策略';

const users = [
  { name: '王迎港', email: 'wyg@example.com', role: '超级管理员', status: '活跃', lastActive: '刚刚' },
  { name: '张晓明', email: 'zhang@example.com', role: '数据负责人', status: '活跃', lastActive: '8 分钟前' },
  { name: '李文静', email: 'li@example.com', role: '数据分析师', status: '活跃', lastActive: '1 小时前' },
  { name: '陈洋', email: 'chen@example.com', role: '业务用户', status: '活跃', lastActive: '昨天' },
  { name: '赵敏', email: 'zhao@example.com', role: '业务用户', status: '已停用', lastActive: '7 天前' },
];

const roles = [
  ['超级管理员', '2', '全部工作空间与系统设置', '启用'],
  ['数据负责人', '5', '数据源与语义模型管理', '启用'],
  ['数据分析师', '12', '问数据、看板与评测中心', '启用'],
  ['业务用户', '23', '问数据与已发布内容', '启用'],
];

const policies = [
  ['核心数据只读', '数据分析师', 'SELECT / WITH 查询', '已同步'],
  ['敏感字段脱敏', '业务用户', 'finance.*', '已同步'],
  ['模型发布审批', '数据负责人', '语义模型', '草稿'],
];

const events = [
  ['王迎港发布语义模型 v1.2.3', '10:34 · 财务分析主题 · 成功'],
  ['张晓明创建数据源连接', '10:18 · CRM MySQL · 成功'],
  ['李文静导出经营看板', '09:42 · 经营总览看板 · 成功'],
  ['陈洋尝试访问受限数据表', '09:16 · finance.payroll · 已拒绝'],
];

function UserAvatar({ name }: { name: string }) {
  return <span className="security-avatar"><img src={avatarCircle} alt="" /><b>{name.slice(0, 1)}</b></span>;
}

export function SecurityAuditPage() {
  const [tab, setTab] = useState<SecurityTab>('用户');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('全部状态');
  const [notice, setNotice] = useState('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const filteredUsers = useMemo(() => users.filter((user) => {
    const matchesQuery = `${user.name}${user.email}${user.role}`.toLowerCase().includes(query.trim().toLowerCase());
    return matchesQuery && (status === '全部状态' || user.status === status);
  }), [query, status]);
  const action = (label: string) => setNotice(`${label}入口已完成 UI 落位；用户、权限和审计 API 尚未接入。`);
  const invite = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setInviteOpen(false);
    setNotice('邀请表单已完成本地校验；当前未向后端发送成员邀请。');
  };

  return <div className="settings-surface-page security-audit-page" data-testid="security-audit-page">
    <header className="settings-page-heading">
      <div><h1>用户、角色与审计</h1><p>管理工作空间成员、角色权限和关键操作审计记录。</p></div>
      <div className="settings-heading-actions"><button className="button secondary" type="button" onClick={() => action('导出审计')}>导出审计</button><button className="button primary" type="button" onClick={() => setInviteOpen(true)}>＋ 邀请成员</button></div>
    </header>
    {notice && <div className="settings-inline-notice" role="status"><span>{notice}</span><button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}

    <section className="security-kpis" aria-label="用户与审计指标">
      {[['人', '用户总数', '42'], ['角', '角色数量', '6'], ['活', '近 7 日活跃', '31'], ['审', '今日审计事件', '286']].map(([icon, label, value]) => <article key={label}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong></article>)}
    </section>

    <section className="security-layout">
      <article className="security-table-card">
        <header className="security-table-tools">
          <div className="security-tabs" role="tablist" aria-label="安全管理视图">{(['用户', '角色', '权限策略'] as SecurityTab[]).map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{item}</button>)}</div>
          <div className="security-filters"><label><span className="sr-only">搜索成员</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索姓名、邮箱或角色" /></label><select aria-label="筛选状态" value={status} onChange={(event) => setStatus(event.target.value)}><option>全部状态</option><option>活跃</option><option>已停用</option></select></div>
        </header>

        <div className="security-table-scroll">
          {tab === '用户' && <table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>最后活跃</th><th>操作</th></tr></thead><tbody>{filteredUsers.length ? filteredUsers.map((user) => <tr key={user.email}><td><div className="security-user-cell"><UserAvatar name={user.name} /><div><b>{user.name}</b><small>{user.email}</small></div></div></td><td>{user.role}</td><td><span className={`security-state ${user.status === '活跃' ? 'active' : 'disabled'}`}>{user.status}</span></td><td>{user.lastActive}</td><td><button type="button" onClick={() => action(`编辑 ${user.name}`)}>编辑</button></td></tr>) : <tr><td className="security-empty-row" colSpan={5}>没有符合当前条件的成员</td></tr>}</tbody></table>}
          {tab === '角色' && <table><thead><tr><th>角色</th><th>成员数</th><th>权限范围</th><th>状态</th><th>操作</th></tr></thead><tbody>{roles.map(([name, count, scope, rowStatus]) => <tr key={name}><td><b>{name}</b></td><td>{count} 人</td><td>{scope}</td><td><span className="security-state active">{rowStatus}</span></td><td><button type="button" onClick={() => action(`编辑角色 ${name}`)}>编辑</button></td></tr>)}</tbody></table>}
          {tab === '权限策略' && <table><thead><tr><th>策略</th><th>适用角色</th><th>资源范围</th><th>状态</th><th>操作</th></tr></thead><tbody>{policies.map(([name, role, scope, rowStatus]) => <tr key={name}><td><b>{name}</b></td><td>{role}</td><td>{scope}</td><td><span className={`security-state ${rowStatus === '草稿' ? 'draft' : 'active'}`}>{rowStatus}</span></td><td><button type="button" onClick={() => action(`查看策略 ${name}`)}>查看</button></td></tr>)}</tbody></table>}
        </div>
        <footer className="security-table-footer"><span>{tab === '用户' ? '共 42 位成员 · 当前为静态样例' : `${tab} · UI 演示数据`}</span><div><button type="button" aria-label="上一页" onClick={() => action('上一页')}>‹</button><button type="button" className="active" aria-label="第 1 页">1</button><button type="button" aria-label="下一页" onClick={() => action('下一页')}>›</button></div></footer>
      </article>

      <aside className="security-side-column">
        <article className="role-summary-card"><header><div><h2>角色权限摘要</h2><p>数据分析师</p></div><span>12 人</span></header><div className="permission-grid"><div><small>问数据</small><strong className="allow">允许</strong></div><div><small>语义模型</small><strong>只读</strong></div><div><small>数据源</small><strong>受限</strong></div><div><small>评测中心</small><strong className="allow">允许</strong></div></div><button type="button" onClick={() => { setTab('权限策略'); action('查看完整权限矩阵'); }}>查看完整权限矩阵</button></article>
        <article className="audit-events-card"><header><h2>最新审计事件</h2><button type="button" onClick={() => action('查看全部审计事件')}>查看全部</button></header><div className="audit-timeline">{events.map(([title, meta]) => <div className="audit-event" key={title}><img src={timelineDot} alt="" /><div><b>{title}</b><span>{meta}</span></div></div>)}</div></article>
      </aside>
    </section>

    {inviteOpen && <Modal title="邀请工作空间成员" onClose={() => setInviteOpen(false)}><form className="form-grid" onSubmit={invite}><p className="notice">P1 UI 演示：提交后不会发送邮件，也不会创建真实用户。</p><Field label="姓名"><input name="name" required /></Field><Field label="企业邮箱"><input name="email" type="email" required /></Field><Field label="角色"><select name="role" defaultValue="数据分析师"><option>数据负责人</option><option>数据分析师</option><option>业务用户</option></select></Field><FormActions onCancel={() => setInviteOpen(false)} submitLabel="发送邀请" /></form></Modal>}
  </div>;
}
