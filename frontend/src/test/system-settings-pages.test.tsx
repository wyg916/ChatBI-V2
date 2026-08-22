import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { systemApi } from '../api/system';
import { ApiError } from '../api/client';
import { securityApi } from '../api/security';
import { SecurityAuditPage } from '../pages/SecurityAuditPage';
import { SettingsModelsPage } from '../pages/SettingsModelsPage';

describe('系统设置高保真页面', () => {
  it('从 Backend API 展示模型服务且不在浏览器提供密钥编辑', async () => {
    const user = userEvent.setup();
    vi.spyOn(systemApi, 'modelProviders').mockResolvedValue({
      active_provider: 'kimi',
      secrets_exposed: false,
      items: [
        { id: 'kimi', display_name: 'Moonshot Kimi', model_name: 'kimi-k2.6', base_url: 'https://api.moonshot.cn/v1', configured: true, active: true, external_model: true, structured_output: true, protocol: 'openai-chat-completions', credential_env: 'CHATBI_KIMI_API_KEY' },
        { id: 'mimo', display_name: 'Xiaomi MiMo', model_name: 'mimo-v2.5', base_url: 'https://api.xiaomimimo.com/v1', configured: true, active: false, external_model: true, structured_output: true, protocol: 'openai-chat-completions', credential_env: 'CHATBI_MIMO_API_KEY' },
        { id: 'deepseek', display_name: 'DeepSeek', model_name: 'deepseek-v4-flash', base_url: 'https://api.deepseek.com', configured: true, active: false, external_model: true, structured_output: true, protocol: 'openai-chat-completions', credential_env: 'CHATBI_DEEPSEEK_API_KEY' },
        { id: 'deterministic', display_name: 'Local Semantic Runtime', model_name: 'deterministic-semantic-v1', base_url: null, configured: true, active: false, external_model: false, structured_output: true, protocol: 'local', credential_env: null },
      ],
    });
    render(<MemoryRouter><SettingsModelsPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '系统设置', level: 1 })).toBeInTheDocument();
    expect(await screen.findByText('Xiaomi MiMo')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Moonshot Kimi', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'DeepSeek', level: 3 })).toBeInTheDocument();
    expect(screen.getByText('3/3')).toBeInTheDocument();
    expect(screen.queryByText('UI 演示')).not.toBeInTheDocument();

    const providerSwitch = screen.getByRole('switch', { name: 'Moonshot Kimi当前使用' });
    expect(providerSwitch).toHaveAttribute('aria-checked', 'true');
    expect(providerSwitch).toBeDisabled();
    await user.click(screen.getAllByRole('button', { name: '配置方式 →' })[0]);
    expect(screen.getByRole('status')).toHaveTextContent('浏览器不会接收或显示 API Key');

    expect(screen.getByRole('button', { name: '查询与安全' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '工作空间' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '外观与品牌' })).toBeDisabled();
  });

  it('从 Backend API 展示 ADMIN/ANALYST、权限矩阵与审计事件', async () => {
    const user = userEvent.setup();
    vi.spyOn(securityApi, 'overview').mockResolvedValue({
      current_actor: { id: 'u1', email: 'admin@chatbi.local', display_name: '管理员', role: 'ADMIN', status: 'ACTIVE' },
      user_count: 2, role_count: 2, active_user_count: 2, audit_event_count: 1,
      users: [
        { id: 'u1', email: 'admin@chatbi.local', display_name: '管理员', role: 'ADMIN', status: 'ACTIVE' },
        { id: 'u2', email: 'analyst@chatbi.local', display_name: '数据分析师', role: 'ANALYST', status: 'ACTIVE' },
      ],
      roles: [
        { name: 'ADMIN', permissions: ['audit.read', 'settings.manage'], user_count: 1 },
        { name: 'ANALYST', permissions: ['query.ask', 'datasource.read'], user_count: 1 },
      ],
      audit_events: [{ id: 'e1', actor_email: 'analyst@chatbi.local', action: 'RESOURCE_ACCESS', resource_type: 'DATASOURCE', status: 'DENIED', details: {}, created_at: '2026-08-17T12:00:00Z' }],
    });
    render(<MemoryRouter><SecurityAuditPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '用户、角色与审计', level: 1 })).toBeInTheDocument();
    const search = await screen.findByPlaceholderText('搜索姓名、邮箱或角色');
    await user.type(search, 'analyst');
    expect(screen.getByText('analyst@chatbi.local')).toBeInTheDocument();
    expect(screen.queryByText('admin@chatbi.local')).not.toBeInTheDocument();

    await user.clear(search);
    await user.click(screen.getByRole('tab', { name: '角色' }));
    expect(screen.getAllByText('数据分析师').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: '权限策略' }));
    expect(screen.getByText('query.ask')).toBeInTheDocument();
    expect(screen.getByText(/RESOURCE_ACCESS/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '＋ 邀请成员' })).toBeDisabled();
  });

  it('显示真实 Permission Denied 状态', async () => {
    vi.spyOn(securityApi, 'overview').mockRejectedValue(new ApiError(403, 'Permission denied: audit.read'));
    render(<MemoryRouter><SecurityAuditPage /></MemoryRouter>);
    expect(await screen.findByTestId('permission-denied')).toHaveTextContent('仅 ADMIN');
  });
});
