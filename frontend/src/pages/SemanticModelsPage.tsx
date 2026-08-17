import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { semanticApi } from '../api/semantic';
import { useDatasources, useSemanticModels } from '../hooks/useData';
import { ErrorNotice, Field, FormActions, Loading, Modal } from '../components/UI';
import type { SemanticModel, SemanticModelInput, SemanticStatus } from '../types/api';
import './semantic.css';

const statusLabels: Record<SemanticStatus, string> = {
  PUBLISHED: '启用中',
  DRAFT: '草稿',
  DEPRECATED: '已停用',
};

function formatVersion(version?: number | string) {
  if (typeof version === 'string') return version.startsWith('v') ? version : `v${version}`;
  return `v${version ?? 1}`;
}

function formatUpdatedAt(value?: string) {
  if (!value) return '尚未更新';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replace('/', '-');
}

function ModelCard({ model }: { model: SemanticModel }) {
  return (
    <Link to={`/semantic-models/${model.id}`} className="semantic-model-card" data-testid="semantic-model-card">
      <div className="semantic-card-head">
        <span className="semantic-model-mark" aria-hidden="true">MOL</span>
        <div className="semantic-card-copy">
          <h2>{model.name}</h2>
          <p title={model.description}>{model.description || '尚未填写模型描述'}</p>
        </div>
        <span className={`semantic-status semantic-status-${model.status.toLowerCase()}`}>{statusLabels[model.status]}</span>
      </div>
      <div className="semantic-card-stats">
        <span><strong>{model.entities?.length ?? 0}</strong><small>业务</small></span>
        <span><strong>{model.metrics?.length ?? 0}</strong><small>度量</small></span>
        <span><strong>{model.relationships?.length ?? 0}</strong><small>关系</small></span>
      </div>
      <footer>
        <span>更新：{formatUpdatedAt(model.updated_at)}</span>
        <b>二维视图 →</b>
      </footer>
    </Link>
  );
}

export function SemanticModelsPage() {
  const models = useSemanticModels();
  const sources = useDatasources();
  const client = useQueryClient();
  const navigate = useNavigate();
  const importInput = useRef<HTMLInputElement>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('ALL');
  const [domain, setDomain] = useState('ALL');
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [importError, setImportError] = useState<Error | null>(null);
  const [form, setForm] = useState<SemanticModelInput>({ name: '', description: '', datasource_id: '' });

  const create = useMutation({
    mutationFn: semanticApi.create,
    onSuccess: (model) => {
      client.invalidateQueries({ queryKey: ['semantic-models'] });
      setShowCreate(false);
      navigate(`/semantic-models/${model.id}`);
    },
  });

  const allModels = models.data ?? [];
  const filtered = useMemo(() => allModels.filter((model) => {
    const query = search.trim().toLowerCase();
    const matchesSearch = !query || `${model.name} ${model.description ?? ''}`.toLowerCase().includes(query);
    const matchesStatus = status === 'ALL' || model.status === status;
    const matchesDomain = domain === 'ALL' || model.datasource_id === domain;
    return matchesSearch && matchesStatus && matchesDomain;
  }), [allModels, domain, search, status]);

  const publishedCount = allModels.filter((model) => model.status === 'PUBLISHED').length;
  const draftCount = allModels.filter((model) => model.status === 'DRAFT').length;
  const recentChanges = [...allModels]
    .sort((left, right) => new Date(right.updated_at ?? 0).getTime() - new Date(left.updated_at ?? 0).getTime())
    .slice(0, showAllHistory ? undefined : 2);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(form);
  };

  const importModel = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text()) as Partial<SemanticModelInput>;
      if (!payload.name || !payload.datasource_id) throw new Error('模型文件必须包含 name 和 datasource_id');
      setImportError(null);
      create.mutate({ name: payload.name, description: payload.description ?? '', datasource_id: payload.datasource_id });
    } catch (error) {
      setImportError(error instanceof Error ? error : new Error('模型文件解析失败'));
    }
  };

  return (
    <section className="semantic-list-page" aria-label="语义模型列表">
      <header className="semantic-list-heading">
        <div>
          <h1>语义模型</h1>
          <p>用统一的业务、度量、口径和关系组织业务，让自然语言查询结果更准确。</p>
        </div>
        <div className="semantic-heading-actions">
          <input ref={importInput} className="visually-hidden" type="file" accept="application/json,.json" onChange={importModel} aria-label="选择语义模型文件" />
          <button className="button secondary" onClick={() => importInput.current?.click()}>导入模型</button>
          <button className="button primary" data-testid="create-model" onClick={() => setShowCreate(true)}>＋ 新建语义模型</button>
        </div>
      </header>

      <ErrorNotice error={models.error ?? sources.error ?? create.error ?? importError} />

      <div className="semantic-filters">
        <label className="semantic-search">
          <span aria-hidden="true">⌕</span>
          <input aria-label="搜索语义模型" placeholder="搜索模型、描述或业务域" value={search} onChange={(event) => setSearch(event.target.value)} />
        </label>
        <select aria-label="按状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="ALL">全部状态</option>
          <option value="PUBLISHED">启用中</option>
          <option value="DRAFT">草稿</option>
          <option value="DEPRECATED">已停用</option>
        </select>
        <select aria-label="按业务域筛选" value={domain} onChange={(event) => setDomain(event.target.value)}>
          <option value="ALL">全部业务域</option>
          {sources.data?.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}
        </select>
        <div className="semantic-counts" aria-label="模型状态统计">
          <span className="semantic-status semantic-status-published">{publishedCount} 个启用中</span>
          <span className="semantic-status semantic-status-draft">{draftCount} 个草稿</span>
        </div>
      </div>

      {models.isLoading ? <Loading /> : (
        <>
          <div className="semantic-model-grid">
            {filtered.map((model) => <ModelCard model={model} key={model.id} />)}
          </div>
          {filtered.length === 0 && (
            <div className="semantic-empty">
              <span aria-hidden="true">模</span>
              <h2>{allModels.length ? '没有符合筛选条件的模型' : '还没有语义模型'}</h2>
              <p>{allModels.length ? '请调整搜索词或筛选条件。' : '关联数据源并定义业务实体、指标和维度。'}</p>
              {!allModels.length && <button className="button primary" onClick={() => setShowCreate(true)}>新建语义模型</button>}
            </div>
          )}
        </>
      )}

      <section className="semantic-history" aria-labelledby="semantic-history-title">
        <header>
          <div><h2 id="semantic-history-title">最近变更记录</h2><p>语义模型的变更、发布和同步历史记录</p></div>
          <button className="button secondary" onClick={() => setShowAllHistory((value) => !value)}>{showAllHistory ? '收起版本记录' : '查看全部版本'}</button>
        </header>
        <div className="semantic-history-scroll">
          <table>
            <thead><tr><th>类型</th><th>版本</th><th>变更内容</th><th>操作人</th><th>状态</th><th>时间</th></tr></thead>
            <tbody>
              {recentChanges.map((model) => (
                <tr key={model.id}>
                  <td>{model.status === 'PUBLISHED' ? '模型发布更新' : '结构变更更新'}</td>
                  <td>{formatVersion(model.version)}</td>
                  <td>更新“{model.name}”语义定义</td>
                  <td>系统同步</td>
                  <td><span className={`semantic-status semantic-status-${model.status.toLowerCase()}`}>{statusLabels[model.status]}</span></td>
                  <td>{formatUpdatedAt(model.updated_at)}</td>
                </tr>
              ))}
              {!recentChanges.length && <tr><td colSpan={6} className="semantic-history-empty">暂无变更记录</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {showCreate && (
        <Modal title="新建语义模型" onClose={() => setShowCreate(false)}>
          <form className="form-grid" onSubmit={submit}>
            <Field label="模型名称"><input name="model-name" required placeholder="例如：新能源经营分析" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
            <Field label="数据源"><select name="datasource" required value={form.datasource_id} onChange={(event) => setForm({ ...form, datasource_id: event.target.value })}><option value="">请选择数据源</option>{sources.data?.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></Field>
            <Field label="描述"><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></Field>
            <ErrorNotice error={create.error} />
            <FormActions busy={create.isPending} onCancel={() => setShowCreate(false)} submitLabel="创建并打开编辑器" />
          </form>
        </Modal>
      )}
    </section>
  );
}
