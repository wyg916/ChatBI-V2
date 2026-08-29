import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { systemApi } from '../api/system';
import type { ModelProviderCatalog, ModelProviderStatus, SystemInformation, WorkspaceSettings } from '../types/api';
import { GovernanceCenterPage, type GovernanceView } from './GovernanceCenterPage';
import './system-settings.css';

const sections = ['模型服务', '查询与安全', '工作空间', '用户与角色', '审计日志', '外观与品牌', '系统信息'] as const;
type Section = (typeof sections)[number];

function providerVisual(provider: ModelProviderStatus) {
  if (provider.id === 'kimi') return { mark: 'KIMI', tone: 'kimi' };
  if (provider.id === 'mimo') return { mark: 'MIMO', tone: 'mimo' };
  if (provider.id === 'deepseek') return { mark: 'DS', tone: 'deepseek' };
  if (provider.id === 'deterministic') return { mark: 'LOCAL', tone: 'local' };
  return { mark: 'OPEN', tone: 'openai' };
}

function formatTime(value?: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '尚未检查';
}

const capabilityLabels: Record<string, string> = {
  general: '通用回答', classification: '意图识别', nl2sql: 'NL2SQL', vision: '图片理解',
  structured: '结构化输出', tool_call: '工具调用', thinking: '复杂推理', stream: '流式输出',
  semantic_fallback: '确定性回退',
};

function providerHealthMessage(value?: string) {
  if (!value || value === 'NOT_CHECKED') return '尚未执行真实连接检查';
  if (value === 'LOCAL_READY') return '本地确定性运行时已就绪';
  if (value === 'HEALTHY') return '真实 Chat Completions 连接成功';
  if (value === 'CREDENTIAL_MISSING') return 'Backend 尚未配置该 Provider 凭据';
  if (value.includes('LEVEL0_PAID_PROVIDER_CALL_BLOCKED')) return '当前为零付费离线验证模式，未发起外部请求';
  if (value.startsWith('AUTH_FAILED')) return '服务端凭据未通过 Provider 验证';
  if (value.startsWith('MODEL_NOT_FOUND')) return 'Provider 未找到当前配置的模型';
  if (value.startsWith('ENDPOINT_UNREACHABLE')) return 'Provider 服务暂时无法连接';
  return value;
}

function providerForCapability(catalog: ModelProviderCatalog | undefined, capability: string, preferredIds: string[] = []) {
  const candidates = catalog?.items
    .filter((item) => item.id !== 'deterministic' && item.configured && (item.enabled ?? item.active) && (item.capabilities ?? []).includes(capability))
    .sort((left, right) => (left.priority ?? 999) - (right.priority ?? 999));
  if (!candidates?.length) return undefined;
  return preferredIds.map((id) => candidates.find((item) => item.id === id)).find(Boolean) ?? candidates[0];
}

function csv(value: string) { return value.split(',').map((item) => item.trim()).filter(Boolean); }
function same(left: unknown, right: unknown) { return JSON.stringify(left) === JSON.stringify(right); }

export function SettingsModelsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [activeSection, setActiveSection] = useState<Section>('模型服务');
  const [catalog, setCatalog] = useState<ModelProviderCatalog>();
  const [saved, setSaved] = useState<WorkspaceSettings>();
  const [draft, setDraft] = useState<WorkspaceSettings>();
  const [system, setSystem] = useState<SystemInformation>();
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([systemApi.modelProviders(), systemApi.settings()]).then(([providers, settings]) => {
      if (!active) return;
      setCatalog(providers); setSaved(settings); setDraft(structuredClone(settings));
    }).catch((reason) => {
      if (!active) return;
      if (reason instanceof ApiError && reason.status === 403) {
        setPermissionDenied(true);
        return;
      }
      setError(reason instanceof Error ? reason.message : '系统设置加载失败');
    });
    return () => { active = false; };
  }, []);

  const dirty = Boolean(saved && draft && (!same(saved.query_security, draft.query_security) || !same(saved.workspace, draft.workspace) || !same(saved.appearance, draft.appearance)));

  async function providerAction(provider: ModelProviderStatus, action: 'test' | 'toggle') {
    setBusy(`${provider.id}:${action}`); setError(''); setNotice('');
    try {
      const value = action === 'test' ? await systemApi.testProvider(provider.id) : await systemApi.setProvider(provider.id, !(provider.enabled ?? provider.active));
      setCatalog((current) => current ? { ...current, items: current.items.map((item) => item.id === value.id ? value : item) } : current);
      if (action === 'test' && value.healthy === false) setError(`${provider.display_name} 连接未通过：${providerHealthMessage(value.health_message)}`);
      else setNotice(action === 'test' ? `${provider.display_name} 连接检查通过：${providerHealthMessage(value.health_message)}` : `${provider.display_name} 已${value.enabled ? '启用' : '禁用'}，刷新后仍会保留。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '模型操作失败'); }
    finally { setBusy(''); }
  }

  async function saveChanges() {
    if (!saved || !draft || !dirty) return;
    const body: Record<string, unknown> = { expected_version: saved.version };
    if (!same(saved.query_security, draft.query_security)) body.query_security = draft.query_security;
    if (!same(saved.workspace, draft.workspace)) body.workspace = draft.workspace;
    if (!same(saved.appearance, draft.appearance)) body.appearance = draft.appearance;
    setBusy('save'); setError(''); setNotice('');
    try {
      const result = await systemApi.saveSettings(body);
      setSaved(result); setDraft(structuredClone(result));
      document.documentElement.style.setProperty('--primary', result.appearance.primary_color);
      window.dispatchEvent(new CustomEvent('chatbi:appearance-updated', { detail: result.appearance }));
      setNotice(`设置已事务保存，版本 ${result.version}。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '设置保存失败，所有变更均已回滚'); }
    finally { setBusy(''); }
  }

  async function selectSection(section: Section) {
    if (section === '用户与角色') { navigate('/settings/security?tab=users'); return; }
    if (section === '审计日志') { navigate('/settings/security?tab=audit'); return; }
    setActiveSection(section);
    if (section === '系统信息') {
      setSystem(undefined); setError('');
      try { setSystem(await systemApi.information()); } catch (reason) { setError(reason instanceof Error ? reason.message : '系统信息加载失败'); }
    }
  }

  const governanceView = searchParams.get('view');
  if (permissionDenied) {
    return <div className="settings-surface-page" data-testid="settings-models-page"><div className="settings-provider-state" role="alert" data-testid="permission-denied">权限不足：仅 ADMIN 可以管理系统设置与模型治理。</div></div>;
  }
  if (governanceView && !catalog && !error) {
    return <div className="settings-surface-page" data-testid="settings-models-page"><div className="settings-provider-state">正在验证管理权限…</div></div>;
  }
  if (governanceView && ['cost', 'trace', 'model', 'evaluation'].includes(governanceView)) return <GovernanceCenterPage view={governanceView as GovernanceView} />;
  const activeProvider = catalog?.items.find((provider) => provider.id === catalog.active_provider);
  const generalProvider = providerForCapability(catalog, 'general', ['mimo', 'deepseek', 'kimi', 'openai-compatible']) ?? activeProvider;
  const nl2sqlProvider = providerForCapability(catalog, 'nl2sql', ['deepseek', 'mimo', 'kimi', 'openai-compatible']) ?? activeProvider;
  const visionProvider = providerForCapability(catalog, 'vision', ['mimo', 'kimi']);
  const premiumProvider = catalog?.items.find((item) => item.id === 'kimi' && item.configured && (item.enabled ?? item.active) && (item.capabilities ?? []).includes('vision'));

  return <div className="settings-surface-page" data-testid="settings-models-page">
    <header className="settings-page-heading">
      <div><h1>系统设置</h1><p>管理模型路由、查询安全、工作空间、品牌和运行信息。</p></div>
      <div className="settings-heading-actions"><button className="button secondary" type="button" onClick={() => navigate('/settings/models?view=model')}>模型治理</button><button className="button primary" type="button" disabled={!dirty || busy === 'save'} title={!dirty ? '没有待保存的变更' : undefined} onClick={() => void saveChanges()}>{busy === 'save' ? '保存中…' : '保存全部设置'}</button></div>
    </header>
    {notice && <div className="settings-inline-notice" role="status"><span>{notice}</span><button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}
    {error && <div className="settings-provider-state error" role="alert">{error}</div>}
    <section className="settings-workspace">
      <nav className="settings-section-nav" aria-label="系统设置分区">{sections.map((section) => <button key={section} type="button" className={activeSection === section ? 'active' : ''} onClick={() => void selectSection(section)}>{section}</button>)}</nav>
      <div className="settings-model-content">
        {activeSection === '模型服务' && <>
          <div className="settings-content-heading"><div><div className="settings-title-row"><h2>模型服务</h2><span>ONE_MODEL_GATEWAY</span>{catalog?.usage_unrestricted && <span>三模型不限内部计费</span>}</div><p>{catalog?.usage_unrestricted ? 'MiMo、DeepSeek、Kimi 均已取消 ChatBI 内部费用上限、复杂度准入和候选次数裁剪；仍保留健康、凭据与回答安全校验。' : '凭据只从 Backend 环境读取；浏览器只接收脱敏运行状态。'}</p></div></div>
          {!catalog && !error && <div className="settings-provider-state">正在读取模型状态…</div>}
          <div className="provider-grid">{catalog?.items.map((provider) => {
            const visual = providerVisual(provider);
            return <article className="provider-card provider-card-functional" key={provider.id}>
              <header className="provider-card-header">
                <div className={`provider-logo ${visual.tone}`}>{visual.mark}</div>
                <div className="provider-copy"><h3>{provider.display_name}</h3><p>{provider.model_name ?? '未选择模型'}</p><small>{provider.id === 'deterministic' ? '本地安全回退' : `唯一 Model Gateway · 优先级 ${provider.priority ?? '—'}`}</small></div>
                <button className="settings-toggle" type="button" role="switch" aria-checked={provider.enabled ?? provider.active} aria-label={`${provider.display_name}${provider.enabled ?? provider.active ? '已启用' : '已禁用'}`} disabled={provider.id === 'deterministic' || Boolean(busy)} onClick={() => void providerAction(provider, 'toggle')}><span>{provider.enabled ?? provider.active ? '开' : '关'}</span></button>
              </header>
              <div className="provider-state-row"><span className={provider.configured ? 'settings-status enabled' : 'settings-status pending'}>{provider.configured ? '已配置' : '未配置'}</span><span className={provider.healthy ? 'settings-status enabled' : provider.healthy === false ? 'settings-status error' : 'settings-status pending'}>{provider.healthy ? '健康' : provider.healthy === false ? '异常' : '未检查'}</span>{['mimo', 'deepseek', 'kimi'].includes(provider.id) && catalog?.usage_unrestricted && <span className="settings-status enabled">不限内部计费</span>}</div>
              <div className="provider-check-time"><span>{providerHealthMessage(provider.health_message)}</span><time>{formatTime(provider.last_checked_at)}</time></div>
              <div className="provider-capabilities" aria-label={`${provider.display_name}能力`}>{(provider.capabilities ?? []).map((item) => <span key={item}>{capabilityLabels[item] ?? item}</span>)}</div>
              <div className="provider-actions"><button type="button" disabled={provider.id === 'deterministic' || !provider.configured || Boolean(busy)} title={!provider.configured ? '请先在 Backend 环境配置凭据' : undefined} onClick={() => void providerAction(provider, 'test')}>{busy === `${provider.id}:test` ? '检测中…' : '测试真实连接'}</button><button type="button" onClick={() => setNotice(`${provider.display_name} 凭据来源：${provider.credential_source}；API Key 不会下发到浏览器。`)}>配置方式</button></div>
            </article>;
          })}</div>
          <article className="settings-detail-card routing-card"><header><h3>当前回答链路</h3><p>{catalog?.selection_strategy ?? '加载中'} · 所有外部 HTTP 仅经 ONE_MODEL_GATEWAY</p></header><div className="routing-table-wrap"><table><thead><tr><th>任务</th><th>首选 Provider</th><th>模型</th><th>发布边界</th></tr></thead><tbody>
            <tr><td>通用回答 / 最终润色</td><td>{generalProvider?.display_name ?? 'Local Semantic Runtime'}</td><td>{generalProvider?.model_name ?? 'deterministic-semantic-v1'}</td><td>验证后呈现</td></tr>
            <tr><td>NL2SQL / 结构化输出</td><td>{nl2sqlProvider?.display_name ?? 'Local Semantic Runtime'}</td><td>{nl2sqlProvider?.model_name ?? 'deterministic-semantic-v1'}</td><td>SQL Guard + Result Oracle</td></tr>
            <tr><td>图片理解</td><td>{visionProvider?.display_name ?? '未配置'}</td><td>{visionProvider?.model_name ?? '—'}</td><td>Visual Evidence Guard</td></tr>
            <tr><td>复杂分析 / 高级视觉</td><td>{premiumProvider?.display_name ?? '未配置'}</td><td>{premiumProvider?.model_name ?? '—'}</td><td>{catalog?.usage_unrestricted ? '可直接路由 + 回答验证' : '质量触发 + 验证门禁'}</td></tr>
            <tr><td>安全回退</td><td>Local Semantic Runtime</td><td>deterministic-semantic-v1</td><td>零外部调用</td></tr>
          </tbody></table></div></article>
        </>}
        {activeSection === '查询与安全' && draft && <SettingsSection title="查询与安全" description="写入当前工作空间并在下一次查询实时生效。"><div className="functional-settings-grid">
          <label>Query Timeout (ms)<input type="number" min={1000} max={120000} value={draft.query_security.query_timeout_ms} onChange={(e) => setDraft({ ...draft, query_security: { ...draft.query_security, query_timeout_ms: Number(e.target.value) } })} /></label>
          <label>Max Rows<input type="number" min={1} max={5000} value={draft.query_security.max_rows} onChange={(e) => setDraft({ ...draft, query_security: { ...draft.query_security, max_rows: Number(e.target.value) } })} /></label>
          <label>SQL Guard Policy<select value={draft.query_security.sql_guard_policy} onChange={(e) => setDraft({ ...draft, query_security: { ...draft.query_security, sql_guard_policy: e.target.value as 'STRICT' | 'STANDARD' } })}><option>STRICT</option><option>STANDARD</option></select></label>
          <label>Allowed Schemas<input value={draft.query_security.allowed_schemas.join(', ')} placeholder="留空表示同步范围内全部" onChange={(e) => setDraft({ ...draft, query_security: { ...draft.query_security, allowed_schemas: csv(e.target.value) } })} /></label>
          <label>Blocked Schemas<input value={draft.query_security.blocked_schemas.join(', ')} onChange={(e) => setDraft({ ...draft, query_security: { ...draft.query_security, blocked_schemas: csv(e.target.value) } })} /></label>
          <div className="mandatory-guards"><b>强制安全门禁</b><span>✓ Read-only Query</span><span>✓ Dangerous SQL Block</span><span>✓ Result Verification</span></div>
        </div></SettingsSection>}
        {activeSection === '工作空间' && draft && <SettingsSection title="工作空间" description={`隔离策略：${draft.workspace_summary.isolation}`}><div className="functional-settings-grid">
          <label>Workspace 名称<input value={draft.workspace.workspace_name} onChange={(e) => setDraft({ ...draft, workspace: { ...draft.workspace, workspace_name: e.target.value } })} /></label>
          <label>状态<select value={draft.workspace.status} onChange={(e) => setDraft({ ...draft, workspace: { ...draft.workspace, status: e.target.value as 'ACTIVE' | 'READ_ONLY' } })}><option value="ACTIVE">ACTIVE</option><option value="READ_ONLY">READ_ONLY</option></select></label>
          <label>默认 Datasource<select value={draft.workspace.default_datasource_id ?? ''} onChange={(e) => setDraft({ ...draft, workspace: { ...draft.workspace, default_datasource_id: e.target.value || null } })}><option value="">自动选择</option>{draft.workspace_summary.datasources.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}</select></label>
          <label>默认 Semantic Model<select value={draft.workspace.default_semantic_model_id ?? ''} onChange={(e) => setDraft({ ...draft, workspace: { ...draft.workspace, default_semantic_model_id: e.target.value || null } })}><option value="">自动选择</option>{draft.workspace_summary.semantic_models.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}</select></label>
          <div className="workspace-facts"><span>成员 <b>{draft.workspace_summary.member_count}</b></span>{Object.entries(draft.workspace_summary.roles).map(([role, count]) => <span key={role}>{role} <b>{count}</b></span>)}</div>
        </div></SettingsSection>}
        {activeSection === '外观与品牌' && draft && <SettingsSection title="外观与品牌" description="保存后全站品牌名称与主色立即刷新并持久化。"><div className="functional-settings-grid appearance-grid">
          <label>产品名称<input value={draft.appearance.product_name} onChange={(e) => setDraft({ ...draft, appearance: { ...draft.appearance, product_name: e.target.value } })} /></label>
          <label>品牌文案<input value={draft.appearance.brand_tagline} onChange={(e) => setDraft({ ...draft, appearance: { ...draft.appearance, brand_tagline: e.target.value } })} /></label>
          <label>Logo URL<input value={draft.appearance.logo_url} placeholder="留空使用内置标识" onChange={(e) => setDraft({ ...draft, appearance: { ...draft.appearance, logo_url: e.target.value } })} /></label>
          <label>主色<input type="color" value={draft.appearance.primary_color} onChange={(e) => setDraft({ ...draft, appearance: { ...draft.appearance, primary_color: e.target.value.toUpperCase() } })} /></label>
          <div className="brand-preview" style={{ borderColor: draft.appearance.primary_color }}><b style={{ color: draft.appearance.primary_color }}>{draft.appearance.product_name}</b><span>{draft.appearance.brand_tagline}</span></div>
        </div></SettingsSection>}
        {activeSection === '系统信息' && <SettingsSection title="系统信息" description="来自当前运行实例、数据库和依赖服务的实时只读状态。">{!system ? <div className="settings-provider-state">正在探测运行状态…</div> : <dl className="system-information-grid">{Object.entries({ 'App Version': system.app_version, 'Git SHA': system.git_sha, 'Release Version': system.release_version, 'Backend Health': system.backend_health, 'Frontend Build': system.frontend_build, 'Database Status': system.database_status, 'Migration Head': system.migration_head, 'RAG Status': system.rag_status, 'Sandbox Status': system.sandbox_status, 'Model Gateway': system.model_gateway_status }).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}</SettingsSection>}
      </div>
    </section>
  </div>;
}

function SettingsSection({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <section className="functional-settings-section"><header><h2>{title}</h2><p>{description}</p></header>{children}</section>;
}
