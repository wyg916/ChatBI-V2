import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Conversation, ConversationShareCreated, Project, SharedConversation } from '../types/api';

const chatMocks = vi.hoisted(() => ({ sharedConversation: vi.fn() }));
vi.mock('../api/chat', () => ({ chatApi: chatMocks }));

import { ConversationSidebar } from '../pages/chat-ui/ConversationSidebar';
import { SharedConversationPage } from '../pages/SharedConversationPage';

const conversations: Conversation[] = [
  { id: 'c1', title: '收入会话', summary: '华东收入', active_attachment_ids: [], project_id: 'p1', created_at: '2026-08-22T01:00:00Z', updated_at: '2026-08-22T01:00:00Z' },
  { id: 'c2', title: '利润会话', summary: '利润趋势', active_attachment_ids: [], created_at: '2026-08-22T02:00:00Z', updated_at: '2026-08-22T02:00:00Z' },
];
const projects: Project[] = [{ id: 'p1', name: '经营项目', description: '', created_at: '2026-08-22T00:00:00Z', updated_at: '2026-08-22T00:00:00Z' }];

function sidebarProps() {
  const createdShare: ConversationShareCreated = {
    id: 's1', conversation_id: 'c1', expires_at: '2026-08-29T00:00:00Z', access_count: 0,
    created_at: '2026-08-22T00:00:00Z', token: 'token-value', share_path: '/share/token-value',
  };
  return {
    conversations, projects, activeId: 'c1', collapsed: false, localEmpty: false, viewState: 'active' as const, projectFilter: '',
    onCollapse: vi.fn(), onNew: vi.fn(), onOpen: vi.fn(), onSearch: vi.fn().mockResolvedValue(undefined),
    onViewState: vi.fn().mockResolvedValue(undefined), onProjectFilter: vi.fn().mockResolvedValue(undefined),
    onRename: vi.fn().mockResolvedValue(undefined), onDelete: vi.fn().mockResolvedValue(undefined),
    onPin: vi.fn().mockResolvedValue(undefined), onArchive: vi.fn().mockResolvedValue(undefined),
    onMoveProject: vi.fn().mockResolvedValue(undefined), onCreateProject: vi.fn().mockResolvedValue(undefined),
    onArchiveProject: vi.fn().mockResolvedValue(undefined), onBatchArchive: vi.fn().mockResolvedValue(undefined),
    onBatchDelete: vi.fn().mockResolvedValue(undefined), onListShares: vi.fn().mockResolvedValue([]),
    onCreateShare: vi.fn().mockResolvedValue(createdShare), onRevokeShare: vi.fn().mockResolvedValue({ ...createdShare, revoked_at: '2026-08-22T03:00:00Z' }),
  };
}

describe('Conversation / Project / Share / Batch UI', () => {
  beforeEach(() => { Object.values(chatMocks).forEach((mock) => mock.mockReset()); });

  it('drives server search, pin, project binding, share and batch archive controls', async () => {
    const user = userEvent.setup();
    const props = sidebarProps();
    render(<ConversationSidebar {...props} />);

    await user.type(screen.getByRole('textbox', { name: '搜索会话' }), '利润');
    await waitFor(() => expect(props.onSearch).toHaveBeenLastCalledWith('利润'), { timeout: 800 });
    await user.clear(screen.getByRole('textbox', { name: '搜索会话' }));

    const income = document.querySelector('[data-conversation-id="c1"]') as HTMLElement;
    await user.click(within(income).getByLabelText('更多操作 收入会话'));
    await user.click(within(income).getByRole('button', { name: '置顶' }));
    await waitFor(() => expect(props.onPin).toHaveBeenCalledWith('c1', true));

    await user.click(within(income).getByLabelText('更多操作 收入会话'));
    await user.selectOptions(within(income).getByRole('combobox', { name: '移动会话 收入会话 到项目' }), '');
    await waitFor(() => expect(props.onMoveProject).toHaveBeenCalledWith('c1', null));

    await user.click(within(income).getByLabelText('更多操作 收入会话'));
    await user.click(within(income).getByRole('button', { name: '共享' }));
    await waitFor(() => expect(props.onListShares).toHaveBeenCalledWith('c1'));
    await user.click(screen.getByRole('button', { name: '创建受控链接' }));
    expect(await screen.findByRole('textbox', { name: '共享链接' })).toHaveValue(`${window.location.origin}/share/token-value`);
    await user.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(props.onRevokeShare).toHaveBeenCalledWith('s1'));
    await user.click(screen.getByRole('button', { name: '关闭共享' }));

    await user.click(screen.getByRole('button', { name: '批量操作' }));
    await user.click(screen.getByRole('checkbox', { name: '选择会话 收入会话' }));
    await user.click(screen.getByRole('button', { name: '批量归档' }));
    await waitFor(() => expect(props.onBatchArchive).toHaveBeenCalledWith(['c1']));
  });

  it('creates and archives projects and switches to archived conversations', async () => {
    const user = userEvent.setup();
    const props = sidebarProps();
    render(<ConversationSidebar {...props} />);
    await user.click(screen.getByLabelText('管理项目'));
    await user.type(screen.getByRole('textbox', { name: '新项目名称' }), '新项目');
    await user.click(screen.getByRole('button', { name: '创建' }));
    await waitFor(() => expect(props.onCreateProject).toHaveBeenCalledWith('新项目'));
    await user.click(screen.getByRole('button', { name: '归档项目 经营项目' }));
    await waitFor(() => expect(props.onArchiveProject).toHaveBeenCalledWith('p1'));
    await user.click(screen.getByRole('button', { name: '已归档' }));
    expect(props.onViewState).toHaveBeenCalledWith('archived');
  });
});

describe('read-only shared conversation page', () => {
  it('renders only the governed public projection and no editing controls', async () => {
    const payload: SharedConversation = {
      share_id: 's1', title: '经营结论', summary: '公开摘要', created_at: '2026-08-22T00:00:00Z',
      updated_at: '2026-08-22T00:00:00Z', expires_at: '2026-08-29T00:00:00Z', read_only: true,
      messages: [{
        id: 'm1', role: 'assistant', content: '<img src=x onerror=alert(1)>安全文本', created_at: '2026-08-22T00:00:00Z',
        message_parts: [{ type: 'table', columns: ['region'], rows: [{ region: '华东' }] }],
      }],
    };
    chatMocks.sharedConversation.mockResolvedValue(payload);
    render(<MemoryRouter initialEntries={['/share/token-value']}><Routes><Route path="/share/:token" element={<SharedConversationPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: '经营结论' })).toBeVisible();
    expect(screen.getByText('<img src=x onerror=alert(1)>安全文本')).toBeVisible();
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByText('华东')).toBeVisible();
    expect(screen.queryByRole('button')).toBeNull();
    expect(chatMocks.sharedConversation).toHaveBeenCalledWith('token-value');
  });
});
