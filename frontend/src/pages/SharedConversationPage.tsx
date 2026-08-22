import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { chatApi } from '../api/chat';
import { EChartsRenderer } from '../charting/EChartsRenderer';
import type { ChartSpec, QueryExecution, SharedConversation } from '../types/api';
import './conversation-share.css';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function SharedPart({ part, execution }: { part: Record<string, unknown>; execution?: QueryExecution }) {
  const type = String(part.type ?? '');
  if (type === 'text') return <p className="shared-text">{String(part.text ?? '')}</p>;
  if (type === 'kpi') {
    const items = Array.isArray(part.items) ? part.items : [];
    return <div className="shared-kpis">{items.map((value, index) => {
      const item = asRecord(value);
      return <div key={`${String(item.label)}-${index}`}><small>{String(item.label ?? '')}</small><strong>{String(item.value ?? '—')}</strong><span>{String(item.unit ?? '')}</span></div>;
    })}</div>;
  }
  if (type === 'table') {
    const columns = Array.isArray(part.columns) ? part.columns.map(String) : [];
    const rows = Array.isArray(part.rows) ? part.rows.map(asRecord) : [];
    return <div className="shared-table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{String(row[column] ?? '—')}</td>)}</tr>)}</tbody></table></div>;
  }
  if (type === 'citations') {
    const items = Array.isArray(part.items) ? part.items : [];
    return <ul className="shared-citations">{items.map((value, index) => {
      const item = asRecord(value);
      return <li key={index}><strong>{String(item.title ?? '来源')}</strong><span>{String(item.version ?? '')}</span><small>{String(item.locator ?? '')}</small></li>;
    })}</ul>;
  }
  if (type === 'chart') {
    const spec = asRecord(part.chart_spec) as unknown as ChartSpec;
    return execution?.rows?.length
      ? <EChartsRenderer spec={spec} execution={execution} label={spec.title || '共享回答图表'} />
      : <div className="shared-chart-placeholder">共享内容未包含图表所需的明细数据</div>;
  }
  if (type === 'error') return <p className="shared-error">{String(part.message ?? '该回答未成功完成。')}</p>;
  return null;
}

export function SharedConversationPage() {
  const { token = '' } = useParams();
  const [conversation, setConversation] = useState<SharedConversation | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    chatApi.sharedConversation(token)
      .then((value) => { if (active) setConversation(value); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '共享内容不可用'); });
    return () => { active = false; };
  }, [token]);

  if (error) return <main className="shared-conversation-state" role="alert"><strong>共享内容不可用</strong><p>{error}</p></main>;
  if (!conversation) return <main className="shared-conversation-state">正在加载只读共享内容…</main>;

  return (
    <main className="shared-conversation-page" data-testid="shared-conversation-page">
      <header>
        <div><span>ChatBI</span><strong>只读共享</strong></div>
        <small>有效至 {new Date(conversation.expires_at).toLocaleString('zh-CN')}</small>
      </header>
      <section className="shared-conversation-card">
        <h1>{conversation.title}</h1>
        {conversation.summary && <p className="shared-summary">{conversation.summary}</p>}
        <div className="shared-messages">
          {conversation.messages.map((message) => {
            const tablePart = message.message_parts.find((part) => part.type === 'table');
            const table = asRecord(tablePart);
            const rows = Array.isArray(table.rows) ? table.rows.map(asRecord) : [];
            const execution = tablePart ? {
              columns: Array.isArray(table.columns) ? table.columns.map(String) : [],
              rows,
              row_count: Number(table.row_count ?? rows.length),
              result_signature: String(table.result_signature ?? ''),
            } satisfies QueryExecution : undefined;
            return <article key={message.id} className={`shared-message ${message.role}`}>
              <small>{message.role === 'user' ? '提问' : 'ChatBI 回答'}</small>
              <p>{message.content}</p>
              {message.role === 'assistant' && message.message_parts.map((part, index) => <SharedPart key={`${message.id}-${index}`} part={part} execution={execution} />)}
            </article>;
          })}
        </div>
      </section>
      <footer>该页面不可编辑、追问或下载私有附件。共享权限由创建者控制。</footer>
    </main>
  );
}
