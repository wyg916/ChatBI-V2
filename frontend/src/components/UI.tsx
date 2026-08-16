import type { FormEvent, ReactNode } from 'react';

export function PageHeading({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div><div className="page-actions">{actions}</div></div>;
}

export function StatusBadge({ status }: { status?: string }) {
  const normalized = (status ?? 'PENDING').toUpperCase();
  const label: Record<string, string> = { CONNECTED: '正常', SYNCED: '已同步', CREATED: '已保存', PUBLISHED: '已发布', DRAFT: '草稿', ERROR: '异常', PENDING: '待连接', DEPRECATED: '已停用' };
  return <span className={`badge badge-${normalized.toLowerCase()}`}>{label[normalized] ?? status}</span>;
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><section className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}><header><h2>{title}</h2><button className="icon-button" aria-label="关闭" onClick={onClose}>×</button></header>{children}</section></div>;
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="notice error">{error instanceof Error ? error.message : '请求失败，请稍后重试'}</div>;
}

export function Loading() { return <div className="loading">正在加载数据…</div>; }

export function FormActions({ busy, onCancel, submitLabel = '保存' }: { busy?: boolean; onCancel: () => void; submitLabel?: string }) {
  return <div className="form-actions"><button type="button" className="button secondary" onClick={onCancel}>取消</button><button className="button primary" disabled={busy}>{busy ? '处理中…' : submitLabel}</button></div>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }

export function stopInvalid(event: FormEvent<HTMLFormElement>) { if (!event.currentTarget.checkValidity()) event.preventDefault(); }
