import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import type { Conversation, ConversationListState, ConversationShare, ConversationShareCreated, Project } from '../../types/api';

const INTERNAL_TITLE_PREFIXES = [
  /^v2\.1-final-load-/i,
  /^day1\s+/i,
  /^day3\s+(?:final|attachment|security)/i,
  /^phase2\s+(?:file|image|follow-up)\s+acceptance/i,
  /^acceptance\s+/i,
] as const;

export function isVisibleConversation(conversation: Conversation) {
  const title = conversation.title.trim();
  return !INTERNAL_TITLE_PREFIXES.some((prefix) => prefix.test(title));
}

type GroupName = '已置顶' | '今天' | '昨天' | '最近 7 天' | '更早';

function groupName(item: Conversation, now = new Date()): GroupName {
  if (item.pinned_at) return '已置顶';
  const date = new Date(item.updated_at || item.created_at);
  if (Number.isNaN(date.getTime())) return '更早';
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const itemDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.floor((today.getTime() - itemDay.getTime()) / 86_400_000);
  if (days <= 0) return '今天';
  if (days === 1) return '昨天';
  if (days < 7) return '最近 7 天';
  return '更早';
}

interface ConversationSidebarProps {
  conversations: Conversation[];
  projects: Project[];
  activeId?: string;
  collapsed: boolean;
  localEmpty: boolean;
  generatingConversationId?: string;
  viewState: ConversationListState;
  projectFilter: string;
  onCollapse: () => void;
  onNew: () => void;
  onOpen: (id: string) => Promise<void> | void;
  onSearch: (query: string) => Promise<void>;
  onViewState: (state: ConversationListState) => Promise<void>;
  onProjectFilter: (projectId: string) => Promise<void>;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onPin: (id: string, pinned: boolean) => Promise<void>;
  onArchive: (id: string, archived: boolean) => Promise<void>;
  onMoveProject: (id: string, projectId: string | null) => Promise<void>;
  onCreateProject: (name: string) => Promise<void>;
  onArchiveProject: (id: string) => Promise<void>;
  onBatchArchive: (ids: string[]) => Promise<void>;
  onBatchDelete: (ids: string[]) => Promise<void>;
  onListShares: (conversationId: string) => Promise<ConversationShare[]>;
  onCreateShare: (conversationId: string, expiresInHours: number) => Promise<ConversationShareCreated>;
  onRevokeShare: (shareId: string) => Promise<ConversationShare>;
}

export function ConversationSidebar({
  conversations,
  projects,
  activeId,
  collapsed,
  localEmpty,
  generatingConversationId,
  viewState,
  projectFilter,
  onCollapse,
  onNew,
  onOpen,
  onSearch,
  onViewState,
  onProjectFilter,
  onRename,
  onDelete,
  onPin,
  onArchive,
  onMoveProject,
  onCreateProject,
  onArchiveProject,
  onBatchArchive,
  onBatchDelete,
  onListShares,
  onCreateShare,
  onRevokeShare,
}: ConversationSidebarProps) {
  const [search, setSearch] = useState('');
  const [renamingId, setRenamingId] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [deleteId, setDeleteId] = useState('');
  const [busyId, setBusyId] = useState('');
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [projectName, setProjectName] = useState('');
  const [shareConversation, setShareConversation] = useState<Conversation | null>(null);
  const [shares, setShares] = useState<ConversationShare[]>([]);
  const [shareUrl, setShareUrl] = useState('');
  const [shareHours, setShareHours] = useState(168);
  const [actionError, setActionError] = useState('');
  const searchMountedRef = useRef(false);

  useEffect(() => {
    if (!searchMountedRef.current) {
      searchMountedRef.current = true;
      return;
    }
    const timer = window.setTimeout(() => { void onSearch(search); }, 250);
    return () => window.clearTimeout(timer);
    // Search is intentionally the only trigger; the parent callback reads the current view filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => {
    const visibleIds = new Set(conversations.map((item) => item.id));
    setSelectedIds((current) => current.filter((id) => visibleIds.has(id)));
  }, [conversations]);

  const groups = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase('zh-CN');
    const visible = conversations
      .filter(isVisibleConversation)
      .filter((item) => !normalizedSearch || `${item.title} ${item.summary}`.toLocaleLowerCase('zh-CN').includes(normalizedSearch));
    const initial: Record<GroupName, Conversation[]> = { 已置顶: [], 今天: [], 昨天: [], '最近 7 天': [], 更早: [] };
    visible.forEach((item) => initial[groupName(item)].push(item));
    return (Object.entries(initial) as Array<[GroupName, Conversation[]]>).filter(([, items]) => items.length > 0);
  }, [conversations, search]);

  const visibleIds = groups.flatMap(([, items]) => items.map((item) => item.id));

  function beginRename(item: Conversation) {
    setDeleteId('');
    setRenamingId(item.id);
    setRenameValue(item.title);
  }

  async function runAction(id: string, action: () => Promise<void>) {
    setBusyId(id);
    setActionError('');
    try {
      await action();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '操作失败');
    } finally {
      setBusyId('');
    }
  }

  async function submitRename(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    const title = renameValue.trim();
    if (!title) return;
    await runAction(id, async () => {
      await onRename(id, title);
      setRenamingId('');
    });
  }

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) return;
    await runAction('project-create', async () => {
      await onCreateProject(name);
      setProjectName('');
    });
  }

  async function openShare(item: Conversation) {
    setShareConversation(item);
    setShareUrl('');
    setActionError('');
    await runAction(`share-${item.id}`, async () => setShares(await onListShares(item.id)));
  }

  async function createShare() {
    if (!shareConversation) return;
    await runAction(`share-${shareConversation.id}`, async () => {
      const created = await onCreateShare(shareConversation.id, shareHours);
      setShares((items) => [created, ...items]);
      setShareUrl(`${window.location.origin}${created.share_path}`);
    });
  }

  async function revokeShare(shareId: string) {
    await runAction(`share-${shareId}`, async () => {
      const revoked = await onRevokeShare(shareId);
      setShares((items) => items.map((item) => item.id === revoked.id ? revoked : item));
    });
  }

  async function runBatch(action: 'archive' | 'delete') {
    if (!selectedIds.length) return;
    await runAction(`batch-${action}`, async () => {
      if (action === 'archive') await onBatchArchive(selectedIds);
      else await onBatchDelete(selectedIds);
      setSelectedIds([]);
      setSelectionMode(false);
    });
  }

  return (
    <aside className={`conversation-panel${collapsed ? ' collapsed' : ''}`} aria-label="会话历史">
      <div className="conversation-panel-head">
        <button type="button" className="new-conversation" onClick={onNew} aria-label="＋ 新会话">
          <span aria-hidden="true">＋</span>{!collapsed && '新会话'}
        </button>
        <button type="button" className="collapse-conversations" onClick={onCollapse} aria-label={collapsed ? '展开会话栏' : '折叠会话栏'}>
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {!collapsed && (
        <>
          <label className="conversation-search">
            <span aria-hidden="true">⌕</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索会话" aria-label="搜索会话" />
          </label>
          <div className="conversation-view-tabs" aria-label="会话状态">
            <button type="button" className={viewState === 'active' ? 'active' : ''} onClick={() => void onViewState('active')}>进行中</button>
            <button type="button" className={viewState === 'archived' ? 'active' : ''} onClick={() => void onViewState('archived')}>已归档</button>
          </div>
          <div className="conversation-project-filter">
            <select aria-label="筛选项目" value={projectFilter} onChange={(event) => void onProjectFilter(event.target.value)}>
              <option value="">全部项目</option>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
            <details>
              <summary aria-label="管理项目">项目</summary>
              <div className="project-manager">
                <form onSubmit={(event) => void submitProject(event)}>
                  <input aria-label="新项目名称" maxLength={255} value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="新项目名称" />
                  <button type="submit" disabled={!projectName.trim() || busyId === 'project-create'}>创建</button>
                </form>
                {projects.map((project) => <div key={project.id}><span>{project.name}</span><button type="button" aria-label={`归档项目 ${project.name}`} onClick={() => void runAction(`project-${project.id}`, () => onArchiveProject(project.id))}>归档</button></div>)}
              </div>
            </details>
          </div>
          <div className="conversation-batch-toolbar">
            <button type="button" onClick={() => { setSelectionMode((value) => !value); setSelectedIds([]); }}>{selectionMode ? '退出批量' : '批量操作'}</button>
            {selectionMode && <>
              <button type="button" onClick={() => setSelectedIds(selectedIds.length === visibleIds.length ? [] : visibleIds)}>{selectedIds.length === visibleIds.length ? '取消全选' : '全选'}</button>
              {viewState === 'active' && <button type="button" disabled={!selectedIds.length} onClick={() => void runBatch('archive')}>批量归档</button>}
              <button type="button" className="danger" disabled={!selectedIds.length} onClick={() => void runBatch('delete')}>批量删除</button>
            </>}
          </div>
        </>
      )}

      <div className="conversation-list">
        {localEmpty && viewState === 'active' && !projectFilter && (
          <div className="conversation-item local active" aria-current="true">
            <span className="conversation-symbol" aria-hidden="true">新</span>
            {!collapsed && <div><strong>新会话</strong><small>发送消息后保存</small></div>}
          </div>
        )}
        {groups.map(([name, items]) => (
          <section className="conversation-group" key={name} aria-labelledby={`conversation-group-${name}`}>
            {!collapsed && <h2 id={`conversation-group-${name}`}>{name}</h2>}
            {items.map((item) => {
              const active = item.id === activeId;
              const generating = item.id === generatingConversationId;
              const selected = selectedIds.includes(item.id);
              return (
                <div key={item.id} data-conversation-id={item.id} className={`conversation-item${active ? ' active' : ''}${generating ? ' generating' : ''}${selected ? ' selected' : ''}`}>
                  {selectionMode && !collapsed && <input type="checkbox" aria-label={`选择会话 ${item.title}`} checked={selected} onChange={() => setSelectedIds((ids) => selected ? ids.filter((id) => id !== item.id) : [...ids, item.id])} />}
                  {renamingId === item.id && !collapsed ? (
                    <form className="conversation-rename" onSubmit={(event) => void submitRename(event, item.id)}>
                      <input autoFocus aria-label={`重命名会话 ${item.title}`} value={renameValue} maxLength={255} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenamingId(''); }} />
                      <button type="submit" disabled={busyId === item.id || !renameValue.trim()}>保存</button>
                      <button type="button" onClick={() => setRenamingId('')}>取消</button>
                    </form>
                  ) : (
                    <>
                      <button type="button" className="conversation-open" title={collapsed ? item.title : undefined} onClick={() => void onOpen(item.id)} aria-current={active ? 'page' : undefined}>
                        <span className="conversation-symbol" aria-hidden="true">{generating ? '···' : item.pinned_at ? '★' : '问'}</span>
                        {!collapsed && <span><strong>{item.title}</strong><small>{generating ? '正在生成回答…' : item.summary || '暂无摘要'}</small></span>}
                      </button>
                      {!collapsed && (
                        <details className="conversation-menu">
                          <summary aria-label={`更多操作 ${item.title}`}>•••</summary>
                          <div>
                            <button type="button" onClick={() => beginRename(item)}>重命名</button>
                            {!item.archived_at && <button type="button" onClick={() => void runAction(item.id, () => onPin(item.id, !item.pinned_at))}>{item.pinned_at ? '取消置顶' : '置顶'}</button>}
                            <button type="button" onClick={() => void runAction(item.id, () => onArchive(item.id, Boolean(item.archived_at)))}>{item.archived_at ? '恢复' : '归档'}</button>
                            <button type="button" onClick={() => void openShare(item)}>共享</button>
                            <label>移动到项目<select aria-label={`移动会话 ${item.title} 到项目`} value={item.project_id ?? ''} onChange={(event) => void runAction(item.id, () => onMoveProject(item.id, event.target.value || null))}><option value="">不属于项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
                            <button type="button" className="danger" onClick={() => { setRenamingId(''); setDeleteId(item.id); }}>删除</button>
                          </div>
                        </details>
                      )}
                    </>
                  )}
                  {deleteId === item.id && !collapsed && (
                    <div className="conversation-delete-confirm" role="alertdialog" aria-label={`确认删除 ${item.title}`}>
                      <p>删除后无法恢复，确定删除此会话？</p>
                      <button type="button" onClick={() => void runAction(item.id, async () => { await onDelete(item.id); setDeleteId(''); })} disabled={busyId === item.id}>确认删除</button>
                      <button type="button" onClick={() => setDeleteId('')}>取消</button>
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        ))}
        {!localEmpty && groups.length === 0 && !collapsed && <p className="conversation-list-empty">{search ? '没有匹配的会话' : '还没有正式会话'}</p>}
      </div>

      {actionError && !collapsed && <p className="conversation-action-error" role="alert">{actionError}</p>}
      {shareConversation && !collapsed && (
        <div className="conversation-share-dialog" role="dialog" aria-modal="true" aria-label={`共享会话 ${shareConversation.title}`}>
          <header><strong>共享“{shareConversation.title}”</strong><button type="button" aria-label="关闭共享" onClick={() => { setShareConversation(null); setShareUrl(''); }}>×</button></header>
          <p>共享页只读，并自动隐藏 SQL、Trace、凭据和私有附件链接。</p>
          <label>有效期<select value={shareHours} onChange={(event) => setShareHours(Number(event.target.value))}><option value={24}>1 天</option><option value={168}>7 天</option><option value={720}>30 天</option></select></label>
          <button type="button" onClick={() => void createShare()} disabled={busyId === `share-${shareConversation.id}`}>创建受控链接</button>
          {shareUrl && <div className="share-created"><input aria-label="共享链接" readOnly value={shareUrl} /><button type="button" onClick={() => void navigator.clipboard?.writeText(shareUrl)}>复制</button></div>}
          <div className="share-list">
            {shares.map((share) => <div key={share.id}><span>{share.revoked_at ? '已撤销' : new Date(share.expires_at) <= new Date() ? '已过期' : `有效至 ${new Date(share.expires_at).toLocaleString('zh-CN')}`}</span>{!share.revoked_at && <button type="button" onClick={() => void revokeShare(share.id)}>撤销</button>}</div>)}
            {shares.length === 0 && <small>尚未创建共享链接</small>}
          </div>
        </div>
      )}
    </aside>
  );
}
