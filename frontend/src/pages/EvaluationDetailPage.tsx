import { useState } from 'react';
import { useParams } from 'react-router-dom';
import timelineStep from '../assets/evaluation/timeline-step.svg';
import './evaluation.css';

const goldenSql = `SELECT r.region_name,
       SUM(o.order_amount) AS revenue,
       (SUM(o.order_amount) / prev.revenue - 1) AS mom
FROM charging_orders o
JOIN region_dimension r ON o.region_code = r.region_code
WHERE o.order_status = 'completed'
  AND o.finish_time >= '2026-06-01'
  AND o.finish_time < '2026-07-01'
GROUP BY r.region_name;`;

const generatedSql = goldenSql.replace("'completed'", "'paid'");

const comparisonRows = [
  { region: '华东', expected: '32,100,000', actual: '32,100,000', difference: '0', expectedMom: '+8.6%', actualMom: '+8.6%', matches: true },
  { region: '东北', expected: '11,200,000', actual: '9,840,000', difference: '-1,360,000', expectedMom: '-5.2%', actualMom: '-8.7%', matches: false },
  { region: '西南', expected: '19,800,000', actual: '18,930,000', difference: '-870,000', expectedMom: '-1.9%', actualMom: '-3.4%', matches: false },
] as const;

const repairSuggestions = [
  ['更新 Verified SQL', '补充“已完成订单”过滤示例'],
  ['增强术语规则', '“收入”默认只统计完成订单'],
  ['加入回归集', '作为过滤口径错误样例长期回归'],
] as const;

const keywordPattern = /('(?:[^']|'')*'|\b(?:SELECT|SUM|AS|FROM|JOIN|ON|WHERE|AND|GROUP BY)\b)/g;
const keywords = new Set(['SELECT', 'SUM', 'AS', 'FROM', 'JOIN', 'ON', 'WHERE', 'AND', 'GROUP BY']);

function normalizeCaseId(id?: string) {
  if (id?.toUpperCase().startsWith('EVAL-')) return id.toUpperCase();
  if (id && /^\d+$/.test(id)) return `EVAL-${id.padStart(5, '0')}`;
  return 'EVAL-00428';
}

function SqlCode({ sql, mismatch }: { sql: string; mismatch?: string }) {
  return <pre className="evaluation-sql"><code>{sql.split(keywordPattern).map((part, index) => {
    if (keywords.has(part)) return <span className="sql-keyword" key={`${part}-${index}`}>{part}</span>;
    if (part.startsWith("'")) return <span className={part === mismatch ? 'sql-value sql-value-mismatch' : 'sql-value'} key={`${part}-${index}`}>{part}</span>;
    return part;
  })}</code></pre>;
}

function PreviewMetric({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'success' | 'danger' }) {
  return <article className={`evaluation-metric ${tone}`}><span>{label}</span><strong>{value}</strong></article>;
}

export function EvaluationDetailPage() {
  const { id } = useParams();
  const [notice, setNotice] = useState('');
  const caseId = normalizeCaseId(id);
  const explainUnavailable = (action: string) => setNotice(`${action}尚未接入 Golden Set 执行 API；当前页面仅用于 UI 评审。`);

  return <section className="evaluation-detail-page">
    <header className="evaluation-page-heading">
      <div><p>评测中心 / Golden Set / 用例 #{caseId} <span>UI 演示 · 未执行</span></p><h1>评测用例详情</h1></div>
      <div className="evaluation-heading-actions">
        <button type="button" disabled title="演示页暂无相邻用例数据">上一条</button>
        <button type="button" disabled title="演示页暂无相邻用例数据">下一条</button>
        <button type="button" className="primary" onClick={() => explainUnavailable('重新运行')}>重新运行</button>
      </div>
    </header>

    {notice && <div className="evaluation-notice" role="status">{notice}</div>}

    <div className="evaluation-layout">
      <div className="evaluation-main-column">
        <article className="evaluation-summary-card">
          <div className="evaluation-question-row">
            <div><span>标准问题</span><h2>2026 年 6 月各区域充电收入及环比变化是多少？</h2></div>
            <div className="evaluation-badges"><span className="danger">结果差异示例</span><span>PostgreSQL</span></div>
          </div>
          <div className="evaluation-metric-grid">
            <PreviewMetric label="SQL 可执行（示例）" value="PASS" tone="success" />
            <PreviewMetric label="结果值准确率（示例）" value="83.3%" tone="danger" />
            <PreviewMetric label="语义匹配（示例）" value="100%" tone="success" />
            <PreviewMetric label="响应时间（示例）" value="2.9s" />
          </div>
        </article>

        <div className="evaluation-sql-grid">
          <article className="evaluation-sql-card"><header><h2>Golden SQL</h2><span className="success">标准示例</span></header><SqlCode sql={goldenSql} /></article>
          <article className="evaluation-sql-card"><header><h2>Generated SQL</h2><span className="danger">差异示例</span></header><SqlCode sql={generatedSql} mismatch="'paid'" /></article>
        </div>

        <article className="evaluation-comparison-card">
          <header><div><h2>结果集对比</h2><p>未执行 · 排序无关比较 · 金额容差 0.01</p></div><span>2 个值差异示例</span></header>
          <div className="evaluation-table-scroll"><table><thead><tr><th>区域</th><th>期望收入</th><th>实际收入</th><th>差异</th><th>期望环比</th><th>实际环比</th><th>状态</th></tr></thead><tbody>
            {comparisonRows.map((row) => <tr key={row.region}><td><strong>{row.region}</strong></td><td>{row.expected}</td><td>{row.actual}</td><td className={row.matches ? '' : 'emphasis'}>{row.difference}</td><td>{row.expectedMom}</td><td>{row.actualMom}</td><td><span className={row.matches ? 'comparison-status success' : 'comparison-status danger'}>{row.matches ? '一致' : '不一致'}</span></td></tr>)}
          </tbody></table></div>
        </article>
      </div>

      <aside className="evaluation-side-column">
        <article className="evaluation-side-card error-card"><h2>错误分类</h2><strong>过滤条件错误（示例）</strong><p>设计示例中的 Generated SQL 使用了 order_status = 'paid'，标准口径示例使用 'completed'；该差异尚未经过实际执行验证。</p></article>
        <article className="evaluation-side-card semantics-card"><h2>业务语义</h2><dl><div><dt>指标</dt><dd>充电收入（示例口径）</dd></div><div><dt>维度</dt><dd>区域、自然月</dd></div><div><dt>标准过滤</dt><dd>订单状态 = 已完成</dd></div></dl></article>
        <article className="evaluation-side-card repair-card"><h2>修复建议</h2><div className="repair-timeline">{repairSuggestions.map(([title, detail]) => <div className="repair-step" key={title}><img src={timelineStep} alt=""/><p><strong>{title}</strong><span>{detail}</span></p></div>)}</div><button type="button" onClick={() => explainUnavailable('创建修复任务')}>创建修复任务</button></article>
      </aside>
    </div>
  </section>;
}
