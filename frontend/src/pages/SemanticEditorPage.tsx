import { useDeferredValue, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { semanticApi } from '../api/semantic';
import { useSemanticModel } from '../hooks/useData';
import { ErrorNotice, Field, FormActions, Loading, Modal } from '../components/UI';
import type { SemanticModel, SemanticResource, SemanticVersion } from '../types/api';
import canvasGrid from '../assets/semantic/canvas-grid.png';
import tagDot from '../assets/semantic/tag-dot.svg';
import toggleOn from '../assets/semantic/toggle-on.svg';
import './semantic.css';

const resourceConfig = {
  entities: { label: '实体', shortLabel: '实体', fields: [['name', '实体名称'], ['source_table', '物理表名'], ['primary_key', '主键'], ['time_dimension', '默认时间维度']] },
  metrics: { label: '度量', shortLabel: '度量', fields: [['name', '度量名称'], ['label', '中文名称'], ['expression', '表达式'], ['aggregation', '聚合方式']] },
  dimensions: { label: '维度', shortLabel: '维度', fields: [['name', '维度名称'], ['label', '中文名称'], ['source_column', '来源字段'], ['type', '数据类型']] },
  relationships: { label: '关系', shortLabel: '关系', fields: [['left_entity', '左实体'], ['right_entity', '右实体'], ['join_type', 'Join 类型'], ['join_keys', '关联键'], ['cardinality', '基数']] },
  'business-terms': { label: '业务术语', shortLabel: '术语', fields: [['term', '术语'], ['synonyms', '同义词'], ['definition', '定义'], ['mapped_object', '映射对象']] },
} as const;

type Kind = keyof typeof resourceConfig;
type ResourceItem = SemanticResource & { id?: string };
type NodePosition = { x: number; y: number };

const NODE_WIDTH = 220;
const NODE_HEIGHT = 144;
const NODE_GAP = 30;
const NODE_PADDING = 28;

function resourceKey(item: ResourceItem, kind: Kind, index: number) {
  const title = kind === 'business-terms' ? item.term : kind === 'relationships' ? `${item.left_entity}-${item.right_entity}` : item.name ?? item.label;
  return String(item.id ?? `${kind}:${title ?? index}`);
}

function autoNodePositions(keys: string[], width: number) {
  const safeWidth = Math.max(width, NODE_WIDTH + NODE_PADDING * 2);
  const columns = Math.max(1, Math.min(3, Math.floor((safeWidth - NODE_PADDING * 2 + NODE_GAP) / (NODE_WIDTH + NODE_GAP))));
  const usedWidth = columns * NODE_WIDTH + (columns - 1) * NODE_GAP;
  const startX = Math.max(NODE_PADDING, (safeWidth - usedWidth) / 2);
  return Object.fromEntries(keys.map((key, index) => [key, {
    x: Math.round(startX + (index % columns) * (NODE_WIDTH + NODE_GAP)),
    y: NODE_PADDING + Math.floor(index / columns) * (NODE_HEIGHT + NODE_GAP),
  }])) as Record<string, NodePosition>;
}

function clampNode(position: NodePosition, width: number, height: number) {
  return {
    x: Math.max(0, Math.min(position.x, Math.max(0, width - NODE_WIDTH))),
    y: Math.max(0, Math.min(position.y, Math.max(0, height - NODE_HEIGHT))),
  };
}

function nodeOverlaps(left: NodePosition, right: NodePosition) {
  const clearance = 10;
  return left.x < right.x + NODE_WIDTH + clearance
    && left.x + NODE_WIDTH + clearance > right.x
    && left.y < right.y + NODE_HEIGHT + clearance
    && left.y + NODE_HEIGHT + clearance > right.y;
}

function nearestFreePosition(key: string, desired: NodePosition, positions: Record<string, NodePosition>, width: number, height: number) {
  const occupied = Object.entries(positions).filter(([otherKey]) => otherKey !== key).map(([, value]) => value);
  const available = (candidate: NodePosition) => !occupied.some((other) => nodeOverlaps(candidate, other));
  const origin = clampNode(desired, width, height);
  if (available(origin)) return origin;
  const step = 26;
  for (let radius = 1; radius <= 24; radius += 1) {
    for (let offset = -radius; offset <= radius; offset += 1) {
      const candidates = [
        { x: origin.x + offset * step, y: origin.y - radius * step },
        { x: origin.x + offset * step, y: origin.y + radius * step },
        { x: origin.x - radius * step, y: origin.y + offset * step },
        { x: origin.x + radius * step, y: origin.y + offset * step },
      ].map((candidate) => clampNode(candidate, width, height));
      const match = candidates.find(available);
      if (match) return match;
    }
  }
  return origin;
}

function itemsFor(model: SemanticModel, kind: Kind): ResourceItem[] {
  if (kind === 'business-terms') return model.business_terms ?? [];
  return model[kind] ?? [];
}

function itemTitle(item: ResourceItem, kind: Kind, index: number) {
  if (kind === 'business-terms') return String(item.term ?? `业务术语 ${index + 1}`);
  if (kind === 'relationships') return `${String(item.left_entity ?? '实体')} → ${String(item.right_entity ?? '实体')}`;
  return String(item.label ?? item.name ?? `${resourceConfig[kind].label} ${index + 1}`);
}

function itemRows(item: ResourceItem, kind: Kind) {
  if (kind === 'entities') return [
    ['#', item.primary_key, '主键'], ['▣', item.source_table, '来源表'], ['◷', item.time_dimension || '未设置', '时间字段'],
  ];
  if (kind === 'metrics') return [
    ['#', item.name, String(item.aggregation ?? '聚合')], ['▣', item.expression, '表达式'], ['●', item.description || '未填写描述', '口径'],
  ];
  if (kind === 'dimensions') return [
    ['#', item.name, String(item.type ?? '类型')], ['▣', item.source_column, '来源字段'], ['●', item.label, '中文名'],
  ];
  if (kind === 'relationships') return [
    ['#', item.left_entity, '左实体'], ['→', item.right_entity, '右实体'], ['▣', item.join_type, String(item.cardinality ?? '基数')],
  ];
  return [
    ['#', item.term, '术语'], ['▣', Array.isArray(item.synonyms) ? item.synonyms.join('、') : item.synonyms, '同义词'], ['→', item.mapped_object, '映射对象'],
  ];
}

function draftFrom(item: ResourceItem | undefined, kind: Kind) {
  if (!item) return {};
  const draft: Record<string, string> = {};
  resourceConfig[kind].fields.forEach(([key]) => {
    const value = item[key];
    if (key === 'synonyms' && Array.isArray(value)) draft[key] = value.join(', ');
    else if (key === 'join_keys' && Array.isArray(value)) {
      draft[key] = value.map((pair) => {
        const entry = pair as { left?: string; right?: string };
        return `${entry.left ?? ''}=${entry.right ?? ''}`;
      }).join(', ');
    } else draft[key] = value == null ? '' : String(value);
  });
  return draft;
}

function payloadFrom(kind: Kind, draft: Record<string, string>, source?: ResourceItem): Record<string, unknown> {
  if (kind === 'business-terms') return {
    term: draft.term,
    synonyms: (draft.synonyms ?? '').split(',').map((value) => value.trim()).filter(Boolean),
    definition: draft.definition,
    mapped_object: draft.mapped_object,
  };
  if (kind === 'relationships') return {
    left_entity: draft.left_entity,
    right_entity: draft.right_entity,
    join_type: draft.join_type || 'LEFT',
    join_keys: (draft.join_keys ?? '').split(',').map((pair) => {
      const [left, right] = pair.split('=').map((value) => value.trim());
      return { left: left || draft.left_entity, right: right || draft.right_entity };
    }).filter((pair) => pair.left && pair.right),
    cardinality: draft.cardinality || 'MANY_TO_ONE',
  };
  if (kind === 'metrics') return {
    name: draft.name,
    label: draft.label,
    expression: draft.expression,
    aggregation: draft.aggregation || 'SUM',
    description: source?.description ?? null,
    filters: source?.filters ?? [],
  };
  if (kind === 'dimensions') return {
    name: draft.name,
    label: draft.label,
    source_column: draft.source_column,
    type: draft.type || 'STRING',
  };
  return {
    name: draft.name,
    source_table: draft.source_table,
    primary_key: draft.primary_key,
    time_dimension: draft.time_dimension || null,
  };
}

function versionLabel(version?: number | string) {
  if (typeof version === 'string') return version.startsWith('v') ? version : `v${version}`;
  return `v${version ?? 1}`;
}

export function SemanticEditorPage() {
  const { id = '' } = useParams();
  const model = useSemanticModel(id);
  const client = useQueryClient();
  const [active, setActive] = useState<Kind>('entities');
  const [adding, setAdding] = useState<Kind | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [resourceSearch, setResourceSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string>();
  const [configDraft, setConfigDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const [previewOpen, setPreviewOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<SemanticVersion[]>([]);
  const [historyError, setHistoryError] = useState<unknown>();
  const deferredResourceSearch = useDeferredValue(resourceSearch);
  const graphViewportRef = useRef<HTMLDivElement>(null);
  const [graphSize, setGraphSize] = useState({ width: 720, height: 500 });
  const [nodePositions, setNodePositions] = useState<Record<string, NodePosition>>({});
  const [layoutReady, setLayoutReady] = useState(false);
  const [dragState, setDragState] = useState<{ key: string; pointerId: number; clientX: number; clientY: number; origin: NodePosition }>();

  const items = useMemo(() => model.data ? itemsFor(model.data, active) : [], [active, model.data]);
  const resourceResults = useQuery({
    queryKey: ['semantic-model-resources', id, active, deferredResourceSearch],
    queryFn: () => semanticApi.searchResources(id, active, deferredResourceSearch),
    enabled: Boolean(id && deferredResourceSearch.trim()),
  });
  const filteredItems = deferredResourceSearch.trim() ? ((resourceResults.data ?? []) as ResourceItem[]) : items;
  const selected = items.find((item) => item.id === selectedId) ?? items[0];
  const allNodeKeys = useMemo(() => items.map((item, index) => resourceKey(item, active, index)), [active, items]);
  const layoutStorageKey = `chatbi:semantic-layout:${id}:${active}`;

  useEffect(() => {
    const element = graphViewportRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const update = () => {
      if (element.clientWidth > 0 && element.clientHeight > 0) setGraphSize({ width: element.clientWidth, height: element.clientHeight });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [model.data]);

  useEffect(() => {
    const automatic = autoNodePositions(allNodeKeys, graphSize.width);
    let saved: Record<string, NodePosition> = {};
    try {
      saved = JSON.parse(localStorage.getItem(layoutStorageKey) ?? '{}') as Record<string, NodePosition>;
    } catch {
      saved = {};
    }
    const rows = Math.max(1, Math.ceil(allNodeKeys.length / Math.max(1, Math.floor((graphSize.width - NODE_PADDING * 2 + NODE_GAP) / (NODE_WIDTH + NODE_GAP)))));
    const height = Math.max(graphSize.height, NODE_PADDING * 2 + rows * NODE_HEIGHT + Math.max(0, rows - 1) * NODE_GAP);
    const next: Record<string, NodePosition> = {};
    allNodeKeys.forEach((key) => {
      const requested = saved[key] && Number.isFinite(saved[key].x) && Number.isFinite(saved[key].y) ? saved[key] : automatic[key];
      next[key] = nearestFreePosition(key, requested, next, graphSize.width, height);
    });
    setNodePositions(next);
    setLayoutReady(true);
  }, [allNodeKeys, graphSize.height, graphSize.width, layoutStorageKey]);

  useEffect(() => {
    if (!layoutReady) return;
    try {
      localStorage.setItem(layoutStorageKey, JSON.stringify(nodePositions));
    } catch {
      // Browser storage may be disabled; the in-memory layout remains stable for this session.
    }
  }, [layoutReady, layoutStorageKey, nodePositions]);

  useEffect(() => {
    const next = items[0];
    setSelectedId(next?.id);
    setConfigDraft(draftFrom(next, active));
  }, [active, model.data]);

  useEffect(() => {
    setConfigDraft(draftFrom(selected, active));
  }, [active, selectedId]);

  const add = useMutation({
    mutationFn: ({ kind, payload }: { kind: Kind; payload: Record<string, unknown> }) => semanticApi.add(id, kind, payload as never),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['semantic-model', id] });
      setAdding(null);
      setForm({});
      setMessage('资源已保存到模型草稿');
    },
  });

  const save = useMutation({
    mutationFn: async () => {
      if (!model.data) return;
      if (selected?.id) await semanticApi.updateResource(id, active, selected.id, payloadFrom(active, configDraft, selected) as never);
      return semanticApi.update(id, { name: model.data.name, description: model.data.description, datasource_id: model.data.datasource_id });
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['semantic-model', id] });
      setMessage('模型草稿已保存');
    },
  });

  const publish = useMutation({
    mutationFn: () => semanticApi.publish(id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['semantic-model', id] });
      setMessage('语义模型已发布，可用于问数据');
    },
  });

  const rollback = useMutation({
    mutationFn: (version: number) => semanticApi.rollback(id, version),
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ['semantic-model', id] });
      setHistory(await semanticApi.versions(id));
      setMessage(`已从历史版本恢复并发布为 v${result.version}`);
    },
  });

  const openHistory = async () => {
    setHistoryOpen(true);
    setHistoryError(undefined);
    try {
      setHistory(await semanticApi.versions(id));
    } catch (reason) {
      setHistoryError(reason);
    }
  };

  if (model.isLoading) return <Loading />;
  if (!model.data) return <ErrorNotice error={model.error ?? new Error('未找到语义模型')} />;

  const config = resourceConfig[active];
  const allResources = (Object.keys(resourceConfig) as Kind[]).flatMap((kind) => itemsFor(model.data!, kind));
  const fieldValues = allResources.flatMap((item) => Object.entries(item).filter(([key]) => key !== 'id').map(([, value]) => value));
  const totalFields = fieldValues.length;
  const alignedFields = fieldValues.filter((value) => value !== '' && value !== null && value !== undefined && (!Array.isArray(value) || value.length > 0)).length;
  const alignmentRate = totalFields ? `${((alignedFields / totalFields) * 100).toFixed(1)}%` : '0.0%';

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!adding) return;
    add.mutate({ kind: adding, payload: payloadFrom(adding, form) });
  };

  const updateSelected = (item: ResourceItem) => {
    setSelectedId(item.id);
    setConfigDraft(draftFrom(item, active));
  };

  const visibleNodes = filteredItems.map((item, index) => ({ item, key: resourceKey(item, active, index), index }));
  const columns = Math.max(1, Math.min(3, Math.floor((graphSize.width - NODE_PADDING * 2 + NODE_GAP) / (NODE_WIDTH + NODE_GAP))));
  const rows = Math.max(1, Math.ceil(allNodeKeys.length / columns));
  const automaticHeight = NODE_PADDING * 2 + rows * NODE_HEIGHT + Math.max(0, rows - 1) * NODE_GAP;
  const positionedHeight = Object.values(nodePositions).reduce((maximum, position) => Math.max(maximum, position.y + NODE_HEIGHT + NODE_PADDING), 0);
  const graphSurfaceHeight = Math.max(graphSize.height, automaticHeight, positionedHeight);
  const visibleEntityKeys = new Map(visibleNodes.map(({ item, key }) => [String(item.name ?? item.source_table ?? ''), key]));
  const relationshipLines = active === 'entities' ? (model.data.relationships ?? []).flatMap((relationship, index) => {
    const fromKey = visibleEntityKeys.get(String(relationship.left_entity));
    const toKey = visibleEntityKeys.get(String(relationship.right_entity));
    const from = fromKey ? nodePositions[fromKey] : undefined;
    const to = toKey ? nodePositions[toKey] : undefined;
    if (!fromKey || !toKey || !from || !to) return [];
    const startX = from.x + NODE_WIDTH / 2;
    const startY = from.y + NODE_HEIGHT / 2;
    const endX = to.x + NODE_WIDTH / 2;
    const endY = to.y + NODE_HEIGHT / 2;
    const bend = Math.max(36, Math.abs(endX - startX) * 0.42);
    return [{ key: String(relationship.id ?? `relationship-${index}`), path: `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}` }];
  }) : [];

  const startNodeDrag = (event: ReactPointerEvent<HTMLButtonElement>, item: ResourceItem, key: string) => {
    const position = nodePositions[key];
    if (!position) return;
    updateSelected(item);
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragState({ key, pointerId: event.pointerId, clientX: Number.isFinite(event.clientX) ? event.clientX : 0, clientY: Number.isFinite(event.clientY) ? event.clientY : 0, origin: position });
  };

  const moveNode = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    const clientX = Number.isFinite(event.clientX) ? event.clientX : dragState.clientX;
    const clientY = Number.isFinite(event.clientY) ? event.clientY : dragState.clientY;
    const next = clampNode({
      x: dragState.origin.x + clientX - dragState.clientX,
      y: dragState.origin.y + clientY - dragState.clientY,
    }, graphSize.width, graphSurfaceHeight);
    setNodePositions((current) => ({ ...current, [dragState.key]: next }));
  };

  const finishNodeDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    setNodePositions((current) => ({
      ...current,
      [dragState.key]: nearestFreePosition(dragState.key, current[dragState.key] ?? dragState.origin, current, graphSize.width, graphSurfaceHeight),
    }));
    setDragState(undefined);
  };

  const moveNodeWithKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>, key: string) => {
    const direction: Record<string, NodePosition> = {
      ArrowLeft: { x: -1, y: 0 }, ArrowRight: { x: 1, y: 0 }, ArrowUp: { x: 0, y: -1 }, ArrowDown: { x: 0, y: 1 },
    };
    const delta = direction[event.key];
    if (!delta) return;
    event.preventDefault();
    const step = event.shiftKey ? 40 : 12;
    setNodePositions((current) => {
      const origin = current[key] ?? { x: 0, y: 0 };
      const requested = { x: origin.x + delta.x * step, y: origin.y + delta.y * step };
      return { ...current, [key]: nearestFreePosition(key, requested, current, graphSize.width, graphSurfaceHeight) };
    });
  };

  return (
    <section className="semantic-editor-page" aria-label="语义模型编辑器">
      <header className="semantic-editor-heading">
        <div className="semantic-editor-title"><h1>模型编辑器</h1><span>{model.data.updated_at ? `数据库更新：${new Date(model.data.updated_at).toLocaleString('zh-CN', { hour12: false })}` : '数据库更新时间：—'}</span></div>
        <div className="semantic-heading-actions">
          <button className="button secondary" onClick={() => setPreviewOpen(true)}>预览数据</button>
          <button className="button secondary" data-testid="version-history" onClick={openHistory}>版本历史</button>
          <button className="button secondary" data-testid="save-model" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? '保存中…' : '保存模型'}</button>
          <button className="button primary" data-testid="publish-model" disabled={publish.isPending} onClick={() => publish.mutate()}>发布 {versionLabel(model.data.version)}</button>
        </div>
      </header>

      {message && <div className="semantic-editor-message" role="status">{message}</div>}
      <ErrorNotice error={model.error ?? resourceResults.error ?? add.error ?? save.error ?? publish.error} />
      <ErrorNotice error={historyError ?? rollback.error} />

      <div className="semantic-editor-shell">
        <aside className="semantic-resource-panel">
          <div className="semantic-resource-title"><strong>模型资源</strong><button aria-label={`添加${config.label}`} onClick={() => { setAdding(active); setForm({}); }}>＋</button></div>
          <label className="semantic-search compact"><span aria-hidden="true">⌕</span><input aria-label="搜索模型资源" placeholder="搜索资源名称" value={resourceSearch} onChange={(event) => setResourceSearch(event.target.value)} /></label>
          <p className="semantic-panel-caption">实体类型</p>
          <div className="semantic-resource-kinds">
            {(Object.keys(resourceConfig) as Kind[]).map((kind) => (
              <button className={active === kind ? 'active' : ''} onClick={() => setActive(kind)} key={kind}>
                <span>{resourceConfig[kind].label}</span><b>{itemsFor(model.data!, kind).length}</b>
              </button>
            ))}
          </div>
          <p className="semantic-panel-caption">标签</p>
          <div className="semantic-resource-tags">
            {['常用实体', model.data.status === 'PUBLISHED' ? '已发布' : '草稿', `版本 ${versionLabel(model.data.version)}`, '主链路模型'].map((tag) => <span key={tag}><img src={tagDot} alt="" />{tag}</span>)}
          </div>
          <p className="semantic-panel-caption">业务过程</p>
          <div className="semantic-process-list"><span>实体 / 维度 / 度量</span><span>关系 / 术语 / 口径</span></div>
        </aside>

        <main className="semantic-graph" style={{ backgroundImage: `url(${canvasGrid})` }} aria-label={`${config.label}关系画布`}>
          <div className="semantic-graph-toolbar"><span>拖动画布卡片可自由排布，位置会自动保存</span><b>{active === 'entities' ? `${relationshipLines.length} 条关系` : `${visibleNodes.length} 个资源`}</b></div>
          <div className="semantic-graph-viewport" ref={graphViewportRef}>
            <div className="semantic-graph-surface" style={{ height: graphSurfaceHeight }}>
              {relationshipLines.length > 0 && <svg className="semantic-connectors" width={graphSize.width} height={graphSurfaceHeight} viewBox={`0 0 ${graphSize.width} ${graphSurfaceHeight}`} aria-hidden="true">
                <defs><marker id="semantic-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker></defs>
                {relationshipLines.map((line) => <path key={line.key} d={line.path} markerEnd="url(#semantic-arrow)" />)}
              </svg>}
              <div className="semantic-graph-nodes">
                {visibleNodes.map(({ item, key, index }) => {
                  const position = nodePositions[key] ?? autoNodePositions([key], graphSize.width)[key];
                  return <button
                    className={`semantic-node ${selected?.id === item.id ? 'active' : ''} ${dragState?.key === key ? 'dragging' : ''}`}
                    data-node-key={key}
                    style={{ transform: `translate3d(${position.x}px, ${position.y}px, 0)` }}
                    onPointerDown={(event) => startNodeDrag(event, item, key)}
                    onPointerMove={moveNode}
                    onPointerUp={finishNodeDrag}
                    onPointerCancel={finishNodeDrag}
                    onKeyDown={(event) => moveNodeWithKeyboard(event, key)}
                    aria-label={`${itemTitle(item, active, index)}，可拖动`}
                    title="拖动调整位置；也可使用方向键微调"
                    key={key}
                  >
                    <header><strong>{itemTitle(item, active, index)}</strong><span>{config.shortLabel}</span></header>
                    {itemRows(item, active).map(([icon, value, label], rowIndex) => (
                      <div className="semantic-node-row" key={`${String(value)}-${rowIndex}`}><span><i>{String(icon)}</i>{String(value ?? '未设置')}</span><small>{String(label)}</small></div>
                    ))}
                  </button>;
                })}
              </div>
              {!filteredItems.length && <div className="semantic-graph-empty"><span>{config.shortLabel[0]}</span><h2>暂无{config.label}</h2><p>从左侧当前类型中添加资源，继续完善语义模型。</p><button className="button primary" onClick={() => setAdding(active)}>添加{config.label}</button></div>}
            </div>
          </div>
          <section className="semantic-alignment" aria-labelledby="alignment-title">
            <header><div><h2 id="alignment-title">命名语义对齐</h2><p>基于语义命名规范识别字段命名差异与潜在异常</p></div><span>{alignedFields}/{totalFields} 已定义</span><button className="button primary" onClick={() => setMessage(`语义对齐检查：${alignedFields}/${totalFields} 个字段具备有效定义`)}>运行对齐</button></header>
            <div><article><small>总字段数</small><strong>{totalFields}</strong></article><article><small>对齐字段</small><strong>{alignedFields}</strong></article><article><small>对齐率</small><strong>{alignmentRate}</strong></article></div>
          </section>
        </main>

        <aside className="semantic-config-panel">
          <h2>{config.label}配置</h2>
          {selected ? config.fields.map(([key, label]) => (
            <label key={key}><span>{label}</span><input value={configDraft[key] ?? ''} onChange={(event) => setConfigDraft({ ...configDraft, [key]: event.target.value })} /></label>
          )) : <p className="semantic-config-empty">选择画布中的资源后编辑配置。</p>}
          <hr />
          <div className="semantic-policy"><div><strong>查询缓存策略</strong><small>V1.3.0 不提供持久化配置</small></div><button aria-label="查询缓存策略" disabled title="当前版本不提供缓存策略配置"><img src={toggleOn} alt="" /></button></div>
          <div className="semantic-policy"><div><strong>全量缓存策略</strong><small>V1.3.0 不提供持久化配置</small></div><button aria-label="全量缓存策略" disabled title="当前版本不提供缓存策略配置"><img src={toggleOn} alt="" /></button></div>
          <hr />
          <p className="semantic-panel-caption">可见范围</p>
          <div className="semantic-scope">{['全部', '部门', '角色', '成员'].map((item) => <button className={item === '全部' ? 'active' : ''} disabled title="当前版本不提供可见范围持久化配置" key={item}>{item}</button>)}</div>
        </aside>
      </div>

      {historyOpen && <Modal title="语义模型版本历史" onClose={() => setHistoryOpen(false)}><div className="semantic-version-list" data-testid="semantic-version-history">{history.length ? history.map((item) => <article key={item.id}><div><strong>v{item.version}</strong><span>{item.is_current ? '当前版本' : new Date(item.published_at).toLocaleString('zh-CN')}</span></div><button className="button secondary" type="button" disabled={item.is_current || rollback.isPending} onClick={() => rollback.mutate(item.version)}>{item.is_current ? '当前' : '回滚到此版本'}</button></article>) : <p className="notice">尚无已发布版本。</p>}</div></Modal>}

      {adding && (
        <Modal title={`添加${resourceConfig[adding].label}`} onClose={() => setAdding(null)}>
          <form className="form-grid" onSubmit={submit}>
            {resourceConfig[adding].fields.map(([key, label]) => <Field label={label} key={key}><input name={key} required={key !== 'time_dimension'} value={form[key] ?? ''} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></Field>)}
            <ErrorNotice error={add.error} />
            <FormActions busy={add.isPending} onCancel={() => setAdding(null)} submitLabel={`保存${resourceConfig[adding].label}`} />
          </form>
        </Modal>
      )}

      {previewOpen && (
        <Modal title="当前资源预览" onClose={() => setPreviewOpen(false)}>
          <div className="semantic-preview">
            <p>模型：<strong>{model.data.name}</strong></p>
            <p>当前类型：<strong>{config.label}</strong></p>
            {selected && Object.entries(selected).filter(([key]) => key !== 'id').map(([key, value]) => <div key={key}><small>{key}</small><span>{Array.isArray(value) ? JSON.stringify(value) : String(value ?? '-')}</span></div>)}
          </div>
        </Modal>
      )}
    </section>
  );
}
