import { API_BASE, ApiError, api } from './client';
import type { Attachment, ChatInput, ChatResponse, Conversation, ConversationDetail } from '../types/api';

function parseError(response: Response) {
  return response.json().catch(() => ({})).then((body) => {
    if (response.status === 401) window.dispatchEvent(new Event('chatbi:unauthorized'));
    throw new ApiError(response.status, body.detail ?? `请求失败 (${response.status})`);
  });
}

export const chatApi = {
  conversations: () => api<Conversation[]>('/conversations'),
  createConversation: (title = '新会话') => api<Conversation>('/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
  conversation: (id: string) => api<ConversationDetail>(`/conversations/${id}`),
  deleteConversation: (id: string) => api<void>(`/conversations/${id}`, { method: 'DELETE' }),
  attachments: (conversationId: string) => api<Attachment[]>(`/attachments?conversation_id=${encodeURIComponent(conversationId)}`),
  deleteAttachment: (id: string) => api<void>(`/attachments/${id}`, { method: 'DELETE' }),
  upload: (conversationId: string, file: File, onProgress: (percent: number) => void) => new Promise<Attachment>((resolve, reject) => {
    const form = new FormData(); form.append('conversation_id', conversationId); form.append('file', file);
    const request = new XMLHttpRequest();
    request.open('POST', `${API_BASE}/attachments`); request.withCredentials = true;
    request.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    request.onload = () => {
      const body = JSON.parse(request.responseText || '{}');
      if (request.status >= 200 && request.status < 300) resolve(body as Attachment);
      else reject(new ApiError(request.status, body.detail ?? `上传失败 (${request.status})`));
    };
    request.onerror = () => reject(new Error('上传网络错误'));
    request.send(form);
  }),
  stream: async (input: ChatInput, onProgress: (stage: string) => void, signal: AbortSignal): Promise<ChatResponse> => {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input), signal,
    });
    if (!response.ok) return parseError(response);
    if (!response.body) throw new Error('浏览器不支持流式响应');
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let result: ChatResponse | undefined;
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const blocks = buffer.split('\n\n'); buffer = blocks.pop() ?? '';
      for (const block of blocks) {
        const event = block.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim();
        const raw = block.split('\n').find((line) => line.startsWith('data:'))?.slice(5).trim();
        if (!event || !raw) continue;
        const payload = JSON.parse(raw);
        if (event === 'progress') onProgress(payload.stage);
        if (event === 'error') throw new Error(payload.code ?? 'CHAT_STREAM_FAILED');
        if (event === 'result') result = payload as ChatResponse;
      }
      if (done) break;
    }
    if (!result) throw new Error('流式回答未返回最终结果');
    return result;
  },
};
