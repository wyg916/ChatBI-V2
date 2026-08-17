import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { SecurityAuditPage } from '../pages/SecurityAuditPage';
import { SettingsModelsPage } from '../pages/SettingsModelsPage';

describe('系统设置高保真页面', () => {
  it('展示模型服务、静态运行样例并支持本地开关交互', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><SettingsModelsPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '系统设置', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('UI 演示')).toBeInTheDocument();
    expect(screen.getByText('OpenAI Compatible')).toBeInTheDocument();
    expect(screen.getByText('99.7%')).toBeInTheDocument();

    const providerSwitch = screen.getByRole('switch', { name: 'OpenAI Compatible已启用' });
    expect(providerSwitch).toHaveAttribute('aria-checked', 'true');
    await user.click(providerSwitch);
    expect(providerSwitch).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('status')).toHaveTextContent('尚未写入后端');

    await user.click(screen.getByRole('button', { name: '查询与安全' }));
    expect(screen.getByRole('heading', { name: '查询与安全' })).toBeInTheDocument();
    expect(screen.getByText(/尚未接入可持久化的后端配置/)).toBeInTheDocument();
  });

  it('提供成员搜索、角色切换和不写后端的邀请表单', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><SecurityAuditPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '用户、角色与审计', level: 1 })).toBeInTheDocument();
    const search = screen.getByPlaceholderText('搜索姓名、邮箱或角色');
    await user.type(search, '赵敏');
    expect(screen.getByText('赵敏')).toBeInTheDocument();
    expect(screen.queryByText('王迎港')).not.toBeInTheDocument();

    await user.clear(search);
    await user.click(screen.getByRole('tab', { name: '角色' }));
    expect(screen.getByText('全部工作空间与系统设置')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '＋ 邀请成员' }));
    expect(screen.getByRole('dialog', { name: '邀请工作空间成员' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('姓名'), '测试成员');
    await user.type(screen.getByLabelText('企业邮箱'), 'member@example.com');
    await user.click(screen.getByRole('button', { name: '发送邀请' }));
    expect(screen.queryByRole('dialog', { name: '邀请工作空间成员' })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('当前未向后端发送成员邀请');
  });
});
