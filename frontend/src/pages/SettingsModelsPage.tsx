import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { systemApi } from '../api/system';
import toggleOff from '../assets/settings/toggle-off.svg';
import toggleOn from '../assets/settings/toggle-on.svg';
import type { ModelProviderCatalog, ModelProviderStatus } from '../types/api';
import { GovernanceCenterPage, type GovernanceView } from './GovernanceCenterPage';
import './system-settings.css';

const sections = ['模型服务', '查询与安全', '工作空间', '用户与角色', '审计日志', '外观与品牌', '系统信息'] as const;

function providerVisual(provider: ModelProviderStatus) {
  if (provider.id === 'kimi') return { mark: 'KIMI', tone: 'kimi' };
  if (provider.id === 'mimo') return { mark: 'MIMO', tone: 'mimo' };
  if (provider.id === 'deepseek') return { mark: 'DS', tone: 'deepseek' };
  if (provider.id === 'deterministic') return { mark: 'LOCAL', tone: 'local' };
  return { mark: 'OPEN', tone: 'openai' };
}

function Toggle({ checked, label }: { checked: boolean; label: string }) {
  return <button className="settings-toggle" type="button" role="switch" aria-checked={checked} aria-label={label} disabled><img src={checked ? toggleOn : toggleOff} alt="" /></button>;
}

export function SettingsModelsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [activeSection, setActiveSection] = useState<(typeof sections)[number]>('模型服务');
  const [catalog, setCatalog] = useState<ModelProviderCatalog | null>(null);
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let cancelled = false;
    systemApi.modelProviders()
      .then((value) => { if (!cancelled) setCatalog(value); })
      .catch(() => { if (!cancelled) setLoadError('模型服务状态加载失败，请确认 Backend API 可用。'); });
    return () => { cancelled = true; };
  }, []);

  const action = (provider: ModelProviderStatus) => {
    const source = provider.credential_env ? `由 Backend 环境变量 ${provider.credential_env} 管理` : '无需外部凭据';
    setNotice(`${provider.display_name} ${source}；浏览器不会接收或显示 API Key。`);
  };
  const selectSection = (section: (typeof sections)[number]) => {
    if (section === '用户与角色' || section === '审计日志') {
      navigate('/settings/security');
      return;
    }
    setActiveSection(section);
  };
  const providers = catalog?.items ?? [];
  const activeProvider = providers.find((provider) => provider.active);
  const namedIds = new Set(['kimi', 'mimo', 'deepseek']);
  const configuredNamed = providers.filter((provider) => namedIds.has(provider.id) && provider.configured).length;
  const governanceView = searchParams.get('view');
  if (governanceView && ['cost', 'trace', 'model', 'evaluation'].includes(governanceView)) {
    return <GovernanceCenterPage view={governanceView as GovernanceView} />;
  }

  return <div className="settings-surface-page" data-testid="settings-models-page">
    <header className="settings-page-heading">
      <div><h1>系统设置</h1><p>管理模型服务、查询策略、用户权限和系统运行配置。</p></div>
      <div className="settings-heading-actions"><button className="button secondary" type="button" onClick={() => navigate('/settings/models?view=model')}>进入模型治理</button><button className="button secondary" type="button" disabled>凭据仅在服务端配置</button><button className="button primary" type="button" disabled>保存全部设置</button></div>
    </header>
    {notice && <div className="settings-inline-notice" role="status"><span>{notice}</span><button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}

    <section className="settings-workspace">
      <nav className="settings-section-nav" aria-label="系统设置分区">
        {sections.map((section) => <button key={section} type="button" className={activeSection === section ? 'active' : ''} onClick={() => selectSection(section)}>{section}</button>)}
      </nav>

      {activeSection === '模型服务' ? <div className="settings-model-content">
        <div className="settings-content-heading">
          <div><div className="settings-title-row"><h2>模型服务</h2><span>Backend API</span></div><p>查看用于 NL2SQL 的服务端模型提供商；API Key 永不下发到浏览器。</p></div>
        </div>

        {!catalog && !loadError && <div className="settings-provider-state" role="status">正在读取服务端模型配置…</div>}
        {loadError && <div className="settings-provider-state error" role="alert">{loadError}</div>}
        {catalog && <div className="provider-grid" aria-label="模型服务列表">
          {providers.map((provider) => {
            const visual = providerVisual(provider);
            const state = provider.active ? '当前使用' : provider.configured ? '已配置' : '未配置';
            return <article className="provider-card" key={provider.id}>
              <div className={`provider-logo ${visual.tone}`}>{visual.mark}</div>
              <div className="provider-copy"><h3>{provider.display_name}</h3><p>{provider.model_name ?? '未选择模型'} · {provider.protocol === 'local' ? '本地语义运行时' : 'OpenAI Compatible'}</p></div>
              <Toggle checked={provider.active} label={`${provider.display_name}${provider.active ? '当前使用' : '未启用'}`} />
              <span className={provider.configured ? 'settings-status enabled' : 'settings-status pending'}>{state}</span>
              <button className="provider-configure" type="button" onClick={() => action(provider)}>配置方式 →</button>
            </article>;
          })}
        </div>}

        <div className="settings-bottom-grid">
          <article className="settings-detail-card routing-card">
            <header><h3>当前 NL2SQL 路由</h3><p>服务端环境变量选择一个 Provider；未配置时安全回退到本地确定性运行时。</p></header>
            <div className="routing-table-wrap"><table><thead><tr><th>任务</th><th>当前 Provider</th><th>模型</th><th>状态</th></tr></thead><tbody><tr><td><b>NL2SQL</b></td><td>{activeProvider?.display_name ?? '加载中'}</td><td>{activeProvider?.model_name ?? '—'}</td><td><span className="settings-status enabled">{activeProvider ? '可用' : '检查中'}</span></td></tr></tbody></table></div>
            <footer><div><b>安全回退</b><span>外部 Provider 未完整配置时使用 deterministic-semantic-v1，不向浏览器暴露凭据</span></div></footer>
          </article>

          <article className="settings-detail-card health-card">
            <header><h3>配置安全状态</h3><p>来自 Backend API 的实时配置摘要</p></header>
            <div className="health-grid"><div><span>指定供应商</span><strong>{configuredNamed}/3</strong></div><div><span>当前路由</span><strong>{activeProvider?.id ?? '—'}</strong></div><div><span>浏览器凭据</span><strong>{catalog?.secrets_exposed ? '异常' : '0'}</strong></div><div><span>JSON 输出</span><strong>ON</strong></div></div>
            <footer><div><b>凭据隔离</b><span>密钥只从 Backend 进程环境读取，状态接口不返回密钥字段</span></div></footer>
          </article>
        </div>
      </div> : <div className="settings-section-placeholder">
        <span>UI</span><h2>{activeSection}</h2><p>该 P1 设置分区已预留在信息架构中，当前尚未接入可持久化的后端配置。</p><button className="button secondary" type="button" onClick={() => setActiveSection('模型服务')}>返回模型服务</button>
      </div>}
    </section>
  </div>;
}
