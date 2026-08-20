import { FormEvent, useMemo, useState } from 'react';
import type { Conversation } from '../../types/api';

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

type GroupName = '今天' | '昨天' | '最近 7 天' | '更早';

function groupName(value: string, now = new Date()): GroupName {
  const date = new Date(value);
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
  activeId?: string;
  collapsed: boolean;
  localEmpty: boolean;
  generatingConversationId?: string;
  onCollapse: () => void;
  onNew: () => void;
  onOpen: (id: string) => Promise<void> | void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function ConversationSidebar({
  conversations,
  activeId,
  collapsed,
  localEmpty,
  generatingConversationId,
  onCollapse,
  onNew,
  onOpen,
  onRename,
  onDelete,
}: ConversationSidebarProps) {
  const [search, setSearch] = useState('');
  const [renamingId, setRenamingId] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [deleteId, setDeleteId] = useState('');
  const [busyId, setBusyId] = useState('');

  const groups = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase('zh-CN');
    const visible = conversations
      .filter(isVisibleConversation)
      .filter((item) => !normalizedSearch || `${item.title} ${item.summary}`.toLocaleLowerCase('zh-CN').includes(normalizedSearch));
    const initial: Record<GroupName, Conversation[]> = { 今天: [], 昨天: [], '最近 7 天': [], 更早: [] };
    visible.forEach((item) => initial[groupName(item.updated_at || item.created_at)].push(item));
    return (Object.entries(initial) as Array<[GroupName, Conversation[]]>).filter(([, items]) => items.length > 0);
  }, [conversations, search]);

  function beginRename(item: Conversation) {
    setDeleteId('');
    setRenamingId(item.id);
    setRenameValue(item.title);
  }

  async function submitRename(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    const title = renameValue.trim();
    if (!title) return;
    setBusyId(id);
    try {
      await onRename(id, title);
      setRenamingId('');
    } finally {
      setBusyId('');
    }
  }

  async function confirmDelete(id: string) {
    setBusyId(id);
    try {
      await onDelete(id);
      setDeleteId('');
    } finally {
      setBusyId('');
    }
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
        <label className="conversation-search">
          <span aria-hidden="true">⌕</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索会话" aria-label="搜索会话" />
        </label>
      )}

      <div className="conversation-list">
        {localEmpty && (
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
              return (
                <div key={item.id} data-conversation-id={item.id} className={`conversation-item${active ? ' active' : ''}${generating ? ' generating' : ''}`}>
                  {renamingId === item.id && !collapsed ? (
                    <form className="conversation-rename" onSubmit={(event) => void submitRename(event, item.id)}>
                      <input autoFocus aria-label={`重命名会话 ${item.title}`} value={renameValue} maxLength={255} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenamingId(''); }} />
                      <button type="submit" disabled={busyId === item.id || !renameValue.trim()}>保存</button>
                      <button type="button" onClick={() => setRenamingId('')}>取消</button>
                    </form>
                  ) : (
                    <>
                      <button type="button" className="conversation-open" title={collapsed ? item.title : undefined} onClick={() => void onOpen(item.id)} aria-current={active ? 'page' : undefined}>
                        <span className="conversation-symbol" aria-hidden="true">{generating ? '···' : '问'}</span>
                        {!collapsed && <span><strong>{item.title}</strong><small>{generating ? '正在生成回答…' : item.summary || '暂无摘要'}</small></span>}
                      </button>
                      {!collapsed && (
                        <details className="conversation-menu">
                          <summary aria-label={`更多操作 ${item.title}`}>•••</summary>
                          <div>
                            <button type="button" onClick={() => beginRename(item)}>重命名</button>
                            <button type="button" className="danger" onClick={() => { setRenamingId(''); setDeleteId(item.id); }}>删除</button>
                          </div>
                        </details>
                      )}
                    </>
                  )}
                  {deleteId === item.id && !collapsed && (
                    <div className="conversation-delete-confirm" role="alertdialog" aria-label={`确认删除 ${item.title}`}>
                      <p>删除后无法恢复，确定删除此会话？</p>
                      <button type="button" onClick={() => void confirmDelete(item.id)} disabled={busyId === item.id}>确认删除</button>
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
    </aside>
  );
}
