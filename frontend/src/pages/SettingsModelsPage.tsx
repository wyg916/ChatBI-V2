import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toggleOff from '../assets/settings/toggle-off.svg';
import toggleOn from '../assets/settings/toggle-on.svg';
import './system-settings.css';

type ProviderKey = 'openai' | 'deepseek' | 'kimi' | 'local';

const sections = ['模型服务', '查询与安全', '工作空间', '用户与角色', '审计日志', '外观与品牌', '系统信息'] as const;

const providers: Array<{ key: ProviderKey; mark: string; name: string; models: string; tone: string; configured: boolean }> = [
  { key: 'openai', mark: 'OPEN', name: 'OpenAI Compatible', models: 'GPT-4.1 / GPT-4o', tone: 'openai', configured: true },
  { key: 'deepseek', mark: 'DS', name: 'DeepSeek', models: 'DeepSeek Chat / Reasoner', tone: 'deepseek', configured: true },
  { key: 'kimi', mark: 'KIMI', name: 'Moonshot Kimi', models: 'Kimi K2 / Kimi-Latest', tone: 'kimi', configured: true },
  { key: 'local', mark: 'LOCAL', name: '本地模型服务', models: 'Qwen / Llama / Mistral', tone: 'local', configured: false },
];

const routingRows = [
  ['NL2SQL', 'GPT-4.1', 'DeepSeek Reasoner'],
  ['业务洞察', 'Kimi K2', 'GPT-4.1'],
  ['评测 Judge', 'GPT-4.1', 'DeepSeek Chat'],
];

function Toggle({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return <button className="settings-toggle" type="button" role="switch" aria-checked={checked} aria-label={label} onClick={onChange}><img src={checked ? toggleOn : toggleOff} alt="" /></button>;
}

export function SettingsModelsPage() {
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<(typeof sections)[number]>('模型服务');
  const [enabled, setEnabled] = useState<Record<ProviderKey, boolean>>({ openai: true, deepseek: true, kimi: true, local: false });
  const [autoFailover, setAutoFailover] = useState(true);
  const [maskLogs, setMaskLogs] = useState(true);
  const [notice, setNotice] = useState('');

  const action = (label: string) => setNotice(`${label}仅作用于当前 UI 演示；模型服务配置 API 尚未接入。`);
  const selectSection = (section: (typeof sections)[number]) => {
    if (section === '用户与角色' || section === '审计日志') {
      navigate('/settings/security');
      return;
    }
    setActiveSection(section);
  };
  const toggleProvider = (provider: (typeof providers)[number]) => {
    if (!provider.configured) {
      setNotice('本地模型服务尚未配置，完成连接参数后才能启用。');
      return;
    }
    setEnabled((current) => ({ ...current, [provider.key]: !current[provider.key] }));
    setNotice(`${provider.name} 的开关已在当前页面更新，尚未写入后端。`);
  };

  return <div className="settings-surface-page" data-testid="settings-models-page">
    <header className="settings-page-heading">
      <div><h1>系统设置</h1><p>管理模型服务、查询策略、用户权限和系统运行配置。</p></div>
      <div className="settings-heading-actions"><button className="button secondary" type="button" onClick={() => action('导出配置')}>导出配置</button><button className="button primary" type="button" onClick={() => action('保存全部设置')}>保存全部设置</button></div>
    </header>
    {notice && <div className="settings-inline-notice" role="status"><span>{notice}</span><button type="button" aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}

    <section className="settings-workspace">
      <nav className="settings-section-nav" aria-label="系统设置分区">
        {sections.map((section) => <button key={section} type="button" className={activeSection === section ? 'active' : ''} onClick={() => selectSection(section)}>{section}</button>)}
      </nav>

      {activeSection === '模型服务' ? <div className="settings-model-content">
        <div className="settings-content-heading">
          <div><div className="settings-title-row"><h2>模型服务</h2><span>UI 演示</span></div><p>配置用于 NL2SQL、业务洞察和评测的模型提供商。</p></div>
          <button className="button primary" type="button" onClick={() => action('添加模型服务')}>＋ 添加模型服务</button>
        </div>

        <div className="provider-grid" aria-label="模型服务列表">
          {providers.map((provider) => <article className="provider-card" key={provider.key}>
            <div className={`provider-logo ${provider.tone}`}>{provider.mark}</div>
            <div className="provider-copy"><h3>{provider.name}</h3><p>{provider.models}</p></div>
            <Toggle checked={enabled[provider.key]} label={`${provider.name}${enabled[provider.key] ? '已启用' : '未启用'}`} onChange={() => toggleProvider(provider)} />
            <span className={provider.configured ? 'settings-status enabled' : 'settings-status pending'}>{provider.configured ? '已启用' : '未配置'}</span>
            <button className="provider-configure" type="button" onClick={() => action(`配置 ${provider.name}`)}>配置 →</button>
          </article>)}
        </div>

        <div className="settings-bottom-grid">
          <article className="settings-detail-card routing-card">
            <header><h3>默认路由策略</h3><p>按任务类型选择首选模型和降级顺序。</p></header>
            <div className="routing-table-wrap"><table><thead><tr><th>任务</th><th>首选模型</th><th>备用模型</th><th>状态</th></tr></thead><tbody>{routingRows.map(([task, primary, fallback]) => <tr key={task}><td><b>{task}</b></td><td>{primary}</td><td>{fallback}</td><td><span className="settings-status enabled">启用</span></td></tr>)}</tbody></table></div>
            <footer><div><b>自动故障转移</b><span>首选模型不可用时切换至备用模型</span></div><Toggle checked={autoFailover} label="自动故障转移" onChange={() => { setAutoFailover((value) => !value); setNotice('自动故障转移仅在当前 UI 演示中更新。'); }} /></footer>
          </article>

          <article className="settings-detail-card health-card">
            <header><h3>服务健康状态</h3><p>最近 15 分钟调用表现 · 静态样例</p></header>
            <div className="health-grid"><div><span>成功率</span><strong>99.7%</strong></div><div><span>平均延迟</span><strong>2.8s</strong></div><div><span>调用量</span><strong>1,284</strong></div><div><span>本月成本</span><strong>¥ 842</strong></div></div>
            <footer><div><b>请求日志脱敏</b><span>自动移除凭证和敏感字段</span></div><Toggle checked={maskLogs} label="请求日志脱敏" onChange={() => { setMaskLogs((value) => !value); setNotice('请求日志脱敏仅在当前 UI 演示中更新。'); }} /></footer>
          </article>
        </div>
      </div> : <div className="settings-section-placeholder">
        <span>UI</span><h2>{activeSection}</h2><p>该 P1 设置分区已预留在信息架构中，当前尚未接入可持久化的后端配置。</p><button className="button secondary" type="button" onClick={() => setActiveSection('模型服务')}>返回模型服务</button>
      </div>}
    </section>
  </div>;
}
