import { useState, type FormEvent } from 'react';
import { contentApi } from '../api/content';
import { ErrorNotice, Field, FormActions, Modal } from '../components/UI';
import type { AnswerInput, DashboardInput } from '../types/api';

type DialogProps = { onClose: () => void; onSaved: () => Promise<void> | void };

export function NewAnswerDialog({ onClose, onSaved }: DialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true); setError(null);
    try {
      await contentApi.createAnswer({
        question: String(data.get('question') ?? ''),
        model_name: String(data.get('model_name') ?? ''),
        owner_name: String(data.get('owner_name') ?? ''),
        module: String(data.get('module') ?? '模块 C1.1.8'),
        status: String(data.get('status') ?? 'DRAFT') as AnswerInput['status'],
        accuracy_percent: Number(data.get('accuracy_percent') ?? 0),
      });
      await onSaved(); onClose();
    } catch (reason) { setError(reason); } finally { setBusy(false); }
  }
  return <Modal title="新建标准答案" onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <Field label="标准问题"><textarea name="question" required minLength={2} placeholder="输入业务人员会提出的标准问题" /></Field>
    <div className="form-columns"><Field label="语义模型"><input name="model_name" required placeholder="例如：全体收入" /></Field><Field label="责任人"><input name="owner_name" required defaultValue="王迎港" /></Field></div>
    <div className="form-columns"><Field label="模块"><input name="module" defaultValue="模块 C1.1.8" required /></Field><Field label="状态"><select name="status" defaultValue="DRAFT"><option value="DRAFT">草稿（需经问数校验后验证）</option></select></Field></div>
    <Field label="当前准确率（%）"><input name="accuracy_percent" type="number" min="0" max="100" step="0.1" defaultValue="0" /></Field>
    <ErrorNotice error={error} /><FormActions busy={busy} onCancel={onClose} submitLabel="保存标准答案" />
  </form></Modal>;
}

export function NewDashboardDialog({ onClose, onSaved }: DialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true); setError(null);
    try {
      await contentApi.createDashboard({
        name: String(data.get('name') ?? ''),
        description: String(data.get('description') ?? ''),
        card_count: Number(data.get('card_count') ?? 0),
        is_shared: data.get('is_shared') === 'on',
      });
      await onSaved(); onClose();
    } catch (reason) { setError(reason); } finally { setBusy(false); }
  }
  return <Modal title="新建看板" onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <Field label="看板名称"><input name="name" required minLength={2} placeholder="例如：经营总览看板" /></Field>
    <Field label="看板说明"><textarea name="description" required minLength={2} placeholder="说明看板覆盖的指标和业务范围" /></Field>
    <Field label="初始卡片数"><input name="card_count" type="number" min="0" defaultValue="0" /></Field>
    <label className="check-row"><input name="is_shared" type="checkbox" /> 创建后共享给当前工作空间</label>
    <ErrorNotice error={error} /><FormActions busy={busy} onCancel={onClose} submitLabel="创建看板" />
  </form></Modal>;
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null; }

export function ContentImportDialog({ kind, onClose, onSaved }: DialogProps & { kind: 'answers' | 'dashboards' }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem('file') as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) { setError(new Error('请选择 JSON 文件')); return; }
    setBusy(true); setError(null);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!Array.isArray(parsed) || !parsed.every(isRecord)) throw new Error('导入文件必须是 JSON 对象数组');
      if (kind === 'answers') {
        await Promise.all(parsed.map((item) => contentApi.createAnswer(item as unknown as AnswerInput)));
      } else {
        await Promise.all(parsed.map((item) => contentApi.createDashboard(item as unknown as DashboardInput)));
      }
      await onSaved(); onClose();
    } catch (reason) { setError(reason instanceof SyntaxError ? new Error('JSON 文件格式不正确') : reason); } finally { setBusy(false); }
  }
  const title = kind === 'answers' ? '批量导入标准答案' : '导入看板模板';
  return <Modal title={title} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <p className="notice">选择 UTF-8 JSON 对象数组；导入内容会经 Backend API 写入元数据库。</p>
    <Field label="JSON 文件"><input name="file" type="file" accept="application/json,.json" required /></Field>
    <ErrorNotice error={error} /><FormActions busy={busy} onCancel={onClose} submitLabel="校验并导入" />
  </form></Modal>;
}
