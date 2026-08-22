import { API_BASE, ApiError, api } from './client';
import { streamChat } from '../chat/stream';
import type {
  Attachment,
  ChatInput,
  ChatResponse,
  ChatStreamEvent,
  ChatStreamHandlers,
  Conversation,
  ConversationBatchResult,
  ConversationDetail,
  ConversationListOptions,
  ConversationShare,
  ConversationShareCreated,
  Project,
  SharedConversation,
} from '../types/api';

type LegacyProgressHandler = (stage: string) => void;

function legacyStage(event: ChatStreamEvent): string | undefined {
  if (event.event_type === 'run.started') return 'UNDERSTANDING';
  if (event.event_type === 'run.completed') return 'COMPLETED';
  if (event.event_type !== 'phase.started' && event.event_type !== 'phase.completed') return undefined;
  if (event.phase === 'retrieving_knowledge') return 'RETRIEVING_KNOWLEDGE';
  if (event.phase === 'verifying') return 'VERIFYING';
  if (event.phase === 'composing_answer') return 'GENERATING_INSIGHT';
  if (event.phase === 'semantic_mapping' || event.phase === 'querying_data') return 'QUERYING_DATA';
  return 'UNDERSTANDING';
}

function normalizeHandlers(handlers: ChatStreamHandlers | LegacyProgressHandler): ChatStreamHandlers {
  if (typeof handlers !== 'function') return handlers;
  return {
    onEvent: (event) => {
      const stage = legacyStage(event);
      if (stage) handlers(stage);
    },
  };
}

function parseUploadBody(responseText: string): Record<string, unknown> {
  try {
    const value = JSON.parse(responseText || '{}') as unknown;
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

function queryPath(path: string, values: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value) query.set(key, value); });
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export const chatApi = {
  conversations: (options: ConversationListOptions = {}) => api<Conversation[]>(queryPath('/conversations', {
    q: options.q, state: options.state, project_id: options.project_id,
  })),
  createConversation: (title = '新会话') => api<Conversation>('/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
  conversation: (id: string) => api<ConversationDetail>(`/conversations/${id}`),
  renameConversation: (id: string, title: string) => api<Conversation>(`/conversations/${id}`, {
    method: 'PATCH', body: JSON.stringify({ title }),
  }),
  deleteConversation: (id: string) => api<void>(`/conversations/${id}`, { method: 'DELETE' }),
  pinConversation: (id: string) => api<Conversation>(`/conversations/${id}/pin`, { method: 'POST' }),
  unpinConversation: (id: string) => api<Conversation>(`/conversations/${id}/unpin`, { method: 'POST' }),
  archiveConversation: (id: string) => api<Conversation>(`/conversations/${id}/archive`, { method: 'POST' }),
  restoreConversation: (id: string) => api<Conversation>(`/conversations/${id}/restore`, { method: 'POST' }),
  batchArchiveConversations: (ids: string[]) => api<ConversationBatchResult>('/conversations/batch/archive', {
    method: 'POST', body: JSON.stringify({ conversation_ids: ids }),
  }),
  batchDeleteConversations: (ids: string[]) => api<ConversationBatchResult>('/conversations/batch/delete', {
    method: 'POST', body: JSON.stringify({ conversation_ids: ids }),
  }),
  projects: (q = '', state: 'active' | 'archived' | 'all' = 'active') => api<Project[]>(queryPath('/projects', { q, state })),
  createProject: (name: string, description = '') => api<Project>('/projects', {
    method: 'POST', body: JSON.stringify({ name, description }),
  }),
  archiveProject: (id: string) => api<Project>(`/projects/${id}/archive`, { method: 'POST' }),
  restoreProject: (id: string) => api<Project>(`/projects/${id}/restore`, { method: 'POST' }),
  moveConversationToProject: (conversationId: string, projectId: string) => api<Conversation>(`/conversations/${conversationId}/project`, {
    method: 'PUT', body: JSON.stringify({ project_id: projectId }),
  }),
  removeConversationFromProject: (conversationId: string) => api<Conversation>(`/conversations/${conversationId}/project`, { method: 'DELETE' }),
  shares: (conversationId: string) => api<ConversationShare[]>(`/conversations/${conversationId}/shares`),
  createShare: (conversationId: string, expiresInHours = 168) => api<ConversationShareCreated>(`/conversations/${conversationId}/shares`, {
    method: 'POST', body: JSON.stringify({ expires_in_hours: expiresInHours }),
  }),
  revokeShare: (shareId: string) => api<ConversationShare>(`/conversation-shares/${shareId}/revoke`, { method: 'POST' }),
  sharedConversation: (token: string) => api<SharedConversation>(`/shared-conversations/${encodeURIComponent(token)}`),
  cancelStream: (conversationId: string, clientMessageId: string) => api<{ cancelled: boolean }>('/chat/stream/cancel', {
    method: 'POST',
    body: JSON.stringify({ conversation_id: conversationId, client_message_id: clientMessageId }),
    keepalive: true,
  }),
  attachments: (conversationId: string) => api<Attachment[]>(`/attachments?conversation_id=${encodeURIComponent(conversationId)}`),
  deleteAttachment: (id: string) => api<void>(`/attachments/${id}`, { method: 'DELETE' }),
  upload: (conversationId: string, file: File, onProgress: (percent: number) => void) => new Promise<Attachment>((resolve, reject) => {
    const form = new FormData(); form.append('conversation_id', conversationId); form.append('file', file);
    const request = new XMLHttpRequest();
    request.open('POST', `${API_BASE}/attachments`); request.withCredentials = true;
    request.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    request.onload = () => {
      const body = parseUploadBody(request.responseText);
      if (request.status >= 200 && request.status < 300) resolve(body as unknown as Attachment);
      else {
        if (request.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('chatbi:unauthorized'));
        const message = typeof body.detail === 'string'
          ? body.detail
          : typeof body.message === 'string'
            ? body.message
            : `上传失败 (${request.status})`;
        reject(new ApiError(request.status, message));
      }
    };
    request.onerror = () => reject(new Error('上传网络错误'));
    request.onabort = () => reject(new DOMException('上传已取消', 'AbortError'));
    request.send(form);
  }),
  stream: (
    input: ChatInput,
    handlers: ChatStreamHandlers | LegacyProgressHandler,
    signal: AbortSignal,
  ): Promise<ChatResponse> => streamChat(input, normalizeHandlers(handlers), signal),
};
