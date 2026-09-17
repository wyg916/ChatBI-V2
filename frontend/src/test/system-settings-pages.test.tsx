import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { systemApi } from '../api/system';
import { ApiError } from '../api/client';
import { securityApi } from '../api/security';
import { SecurityAuditPage } from '../pages/SecurityAuditPage';
import { SettingsModelsPage } from '../pages/SettingsModelsPage';
import type { SecurityOverview } from '../types/api';

describe('系统设置高保真页面', () => {
  it('从 Backend API 展示模型服务且不在浏览器提供密钥编辑', async () => {
    const user = userEvent.setup();
    vi.spyOn(systemApi, 'modelProviders').mockResolvedValue({
      active_provider: 'mimo',
      selection_strategy: 'capability-health-unrestricted',
      usage_unrestricted: true,
      secrets_exposed: false,
      items: [
        { id: 'kimi', display_name: 'Moonshot Kimi', model_name: 'kimi-k2.6', base_url: 'https://api.moonshot.cn/v1', configured: true, enabled: true, active: false, healthy: true, health_message: 'HEALTHY', capabilities: ['general', 'nl2sql', 'vision', 'structured', 'stream'], priority: 3, external_model: true, structured_output: true, protocol: 'openai-chat-completions', credential_env: 'CHATBI_KIMI_API_KEY' },
        { id: 'mimo', display_name: 'Xiaomi MiMo', model_name: 'mimo-v2.5', base_url: 'https://api.xiaomimimo.com/v1', configured: true, enabled: true, active: true, healthy: true, health_message: 'HEALTHY', capabilities: ['general', 'classification', 'nl2sql', 'vision', 'structured', 'stream'], priority: 1, external_model: true, structured_output: true, protocol: 'openai-chat-completions', credential_env: 'CHATBI_MIMO_API_KEY' },
        { id: 'deepseek', display_name: 'DeepSeek', model_name: 'deepseek-v4-flash', base_url: 'https://api.deepseek.com', configured: true, enabled: true, active: false, healthy: true, health_message: 'HEALTHY', capabilities: ['general', 'classification', 'nl2sql', 'structured', 'tool_call', 'stream'], priority: 2, external_model: true, structured_output: true, protocol: 'openai-chat-completions', credential_env: 'CHATBI_DEEPSEEK_API_KEY' },
        { id: 'deterministic', display_name: 'Local Semantic Runtime', model_name: 'deterministic-semantic-v1', base_url: null, configured: true, enabled: true, active: false, healthy: true, health_message: 'LOCAL_READY', capabilities: ['semantic_fallback'], priority: 999, external_model: false, structured_output: true, protocol: 'local', credential_env: null },
      ],
    });
    vi.spyOn(systemApi, 'settings').mockResolvedValue({
      query_security: { query_timeout_ms: 8000, max_rows: 500, read_only_query: true, dangerous_sql_block: true, result_verification: true, sql_guard_policy: 'STRICT', allowed_schemas: [], blocked_schemas: [] },
      workspace: { workspace_name: '默认工作空间', default_datasource_id: null, default_semantic_model_id: null, status: 'ACTIVE' },
      appearance: { product_name: 'ChatBI V2', brand_tagline: '可验证数据答案', logo_url: '', primary_color: '#5B5CF6', theme: 'LIGHT' },
      workspace_summary: { id: 'w1', name: '默认工作空间', member_count: 2, roles: { ADMIN: 1, ANALYST: 1 }, status: 'ACTIVE', isolation: 'WORKSPACE_ID + BACKEND_RBAC', datasources: [], semantic_models: [] },
      version: 1,
    });
    render(<MemoryRouter><SettingsModelsPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '系统设置', level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Xiaomi MiMo', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Moonshot Kimi', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'DeepSeek', level: 3 })).toBeInTheDocument();
    expect(screen.getAllByText('已配置').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('三模型不限内部计费')).toBeInTheDocument();
    expect(screen.getAllByText('不限内部计费').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('可直接路由 + 回答验证')).toBeInTheDocument();
    expect(screen.queryByText('UI 演示')).not.toBeInTheDocument();

    expect(screen.getByText('通用回答 / 最终润色')).toBeInTheDocument();
    expect(screen.getByText('SQL Guard + Result Oracle')).toBeInTheDocument();
    expect(screen.getByText('复杂分析 / 高级视觉')).toBeInTheDocument();
    expect(screen.getAllByText('DeepSeek').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Moonshot Kimi').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByLabelText('Xiaomi MiMo能力')).toHaveTextContent('流式输出');
    expect(screen.getAllByText('真实 Chat Completions 连接成功').length).toBeGreaterThanOrEqual(3);

    const providerSwitch = screen.getByRole('switch', { name: 'Moonshot Kimi已启用' });
    expect(providerSwitch).toHaveAttribute('aria-checked', 'true');
    expect(providerSwitch).toBeEnabled();
    await user.click(screen.getAllByRole('button', { name: '配置方式' })[0]);
    expect(screen.getByRole('status')).toHaveTextContent('API Key 不会下发到浏览器');

    expect(screen.getByRole('button', { name: '查询与安全' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '工作空间' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '外观与品牌' })).toBeEnabled();
  });

  it('从 Backend API 展示 ADMIN/ANALYST、权限矩阵与审计事件', async () => {
    const user = userEvent.setup();
    const overview: SecurityOverview = {
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
      permission_resources: [
        { resource_type: 'DATASOURCE', resource_id: 'ds1', name: '销售数据源' },
        { resource_type: 'SEMANTIC_MODEL', resource_id: 'sm1', name: '经营语义模型' },
      ],
      resource_grants: [
        { id: 'g1', user_id: 'u2', resource_type: 'DATASOURCE', resource_id: 'ds1', can_read: true, can_query: false },
      ],
    };
    const loadOverview = vi.spyOn(securityApi, 'overview').mockImplementation(async (options = {}) => ({
      ...overview,
      users: overview.users.filter((item) => {
        const query = options.query?.toLowerCase() ?? '';
        return (!query || `${item.display_name}${item.email}${item.role}`.toLowerCase().includes(query))
          && (!options.status || options.status === 'ALL' || item.status === options.status);
      }),
    }));
    const savePermission = vi.spyOn(securityApi, 'setResourcePermission').mockResolvedValue({
      id: 'g1', user_id: 'u2', resource_type: 'DATASOURCE', resource_id: 'ds1', can_read: true, can_query: true,
    });
    const revokePermission = vi.spyOn(securityApi, 'revokeResourcePermission').mockResolvedValue(undefined);
    render(<MemoryRouter><SecurityAuditPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '用户、角色与审计', level: 1 })).toBeInTheDocument();
    const search = await screen.findByPlaceholderText('搜索成员或审计');
    await user.type(search, 'analyst');
    await waitFor(() => expect(loadOverview).toHaveBeenCalledWith({ query: 'analyst', status: 'ALL' }));
    expect(await screen.findByText('analyst@chatbi.local')).toBeInTheDocument();
    expect(screen.queryByText('admin@chatbi.local')).not.toBeInTheDocument();

    await user.clear(search);
    await user.click(screen.getByRole('tab', { name: '角色' }));
    expect(screen.getAllByText('数据分析师').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: '权限策略' }));
    expect(screen.getByText('query.ask')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '选择权限成员' })).toHaveValue('u2');
    expect(screen.getByRole('checkbox', { name: '读取 销售数据源' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '查询 销售数据源' })).not.toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: '查询 销售数据源' }));
    await user.click(screen.getByRole('button', { name: '保存 销售数据源 权限' }));
    await waitFor(() => expect(savePermission).toHaveBeenCalledWith('u2', 'DATASOURCE', 'ds1', { can_read: true, can_query: true }));
    await user.click(screen.getByRole('button', { name: '撤销 销售数据源 权限' }));
    await waitFor(() => expect(revokePermission).toHaveBeenCalledWith('u2', 'DATASOURCE', 'ds1'));
    await user.selectOptions(screen.getByRole('combobox', { name: '选择权限成员' }), 'u1');
    expect(screen.getByText('管理员为隐式全权')).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: '资源权限编辑器' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: '审计日志' }));
    expect(screen.getByText(/RESOURCE_ACCESS/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '邀请成员' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '＋ 添加成员' })).toBeEnabled();
  });

  it('兼容尚未返回资源授权字段的旧 Backend 响应', async () => {
    const user = userEvent.setup();
    vi.spyOn(securityApi, 'overview').mockResolvedValue({
      current_actor: { id: 'u1', email: 'admin@chatbi.local', display_name: '管理员', role: 'ADMIN', status: 'ACTIVE' },
      user_count: 1, role_count: 2, active_user_count: 1, audit_event_count: 0,
      users: [{ id: 'u1', email: 'admin@chatbi.local', display_name: '管理员', role: 'ADMIN', status: 'ACTIVE' }],
      roles: [{ name: 'ADMIN', permissions: ['settings.manage'], user_count: 1 }],
      audit_events: [],
    } as unknown as SecurityOverview);

    render(<MemoryRouter><SecurityAuditPage /></MemoryRouter>);
    await user.click(await screen.findByRole('tab', { name: '权限策略' }));

    expect(screen.getByText('管理员为隐式全权')).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: '资源权限编辑器' })).not.toBeInTheDocument();
  });

  it('显示真实 Permission Denied 状态', async () => {
    vi.spyOn(securityApi, 'overview').mockRejectedValue(new ApiError(403, 'Permission denied: audit.read'));
    render(<MemoryRouter><SecurityAuditPage /></MemoryRouter>);
    expect(await screen.findByTestId('permission-denied')).toHaveTextContent('仅 ADMIN');
    expect(screen.queryByRole('button', { name: '邀请成员' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '＋ 添加成员' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '角色' })).not.toBeInTheDocument();
  });

  it('模型设置直达 403 后只保留权限不足状态', async () => {
    vi.spyOn(systemApi, 'modelProviders').mockRejectedValue(new ApiError(403, 'Permission denied: settings.manage'));
    vi.spyOn(systemApi, 'settings').mockRejectedValue(new ApiError(403, 'Permission denied: settings.manage'));
    render(<MemoryRouter initialEntries={['/settings/models']}><SettingsModelsPage /></MemoryRouter>);

    expect(await screen.findByTestId('permission-denied')).toHaveTextContent('仅 ADMIN');
    expect(screen.queryByRole('button', { name: '保存全部设置' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '模型治理' })).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: '系统设置分区' })).not.toBeInTheDocument();
  });
});
