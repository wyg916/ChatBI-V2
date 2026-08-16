import { Link, useParams } from 'react-router-dom';
import { PageHeading, StatusBadge } from '../components/UI';

const copy = {
  answers: ['答案库', '沉淀经过验证的数据答案，统一业务口径。'],
  dashboards: ['看板', '集中查看关键经营指标和业务趋势。'],
  evaluation: ['评测中心', '持续验证自然语言问数的准确性和稳定性。'],
  settings: ['系统设置与模型服务', '配置模型服务、查询限制和系统运行参数。'],
  security: ['用户角色与审计', '管理成员权限并追踪关键操作记录。'],
} as const;

export function LibraryPage({ kind }: { kind: keyof typeof copy }) {
  const [title, description] = copy[kind];
  if (kind === 'settings') return <><PageHeading title={title} description={description} /><div className="settings-grid"><section className="card"><h2>模型服务</h2><p>OpenAI 兼容接口</p><dl><div><dt>状态</dt><dd><StatusBadge status="PENDING" /></dd></div><div><dt>默认模型</dt><dd>尚未配置</dd></div></dl><button className="button primary">添加模型服务</button></section><section className="card"><h2>查询安全</h2><label className="setting-row">单次最大返回行数 <input defaultValue="1000" /></label><label className="setting-row">查询超时（秒） <input defaultValue="30" /></label><p className="notice">只允许执行单条 SELECT / WITH … SELECT 查询。</p></section></div></>;
  if (kind === 'security') return <><PageHeading title={title} description={description} /><section className="card table-card"><table><thead><tr><th>成员</th><th>角色</th><th>状态</th><th>最近活动</th></tr></thead><tbody><tr><td>王迎港</td><td>管理员</td><td><StatusBadge status="CONNECTED" /></td><td>刚刚</td></tr><tr><td>数据分析组</td><td>分析师</td><td><StatusBadge status="CONNECTED" /></td><td>今天 09:42</td></tr></tbody></table></section></>;
  const cards = kind === 'answers' ? [['月度销售经营复盘', '收入、毛利与订单趋势'], ['区域经营差异分析', '华东、华南与西南区域对比']] : kind === 'dashboards' ? [['新能源经营总览', '12 个指标 · 更新于今天'], ['充电站运营看板', '8 个指标 · 更新于昨天']] : [['核心问数回归集', '32 条用例 · 通过率 93.8%'], ['数据源安全规则', '18 条用例 · 通过率 100%']];
  return <><PageHeading title={title} description={description} actions={<button className="button primary">＋ 新建{title}</button>} /><div className="library-grid">{cards.map(([name, sub], i) => <Link className="library-card" to={kind === 'dashboards' ? `/dashboards/${i + 1}` : kind === 'evaluation' ? `/evaluation/${i + 1}` : '/ask/results'} key={name}><span className="card-icon">{title[0]}</span><div><h2>{name}</h2><p>{sub}</p></div><span>→</span></Link>)}</div></>;
}

export function DashboardDetailPage() { const { id } = useParams(); return <><PageHeading title="新能源经营看板" description={`看板 #${id} · 数据更新于 2 分钟前`} /><div className="kpi-row"><article><small>营业收入</small><strong>¥ 1,842 万</strong><em>↑ 12.8%</em></article><article><small>充电订单</small><strong>28,649</strong><em>↑ 8.1%</em></article><article><small>活跃站点</small><strong>326</strong><em>↑ 4.6%</em></article></div><section className="card dashboard-chart"><h2>月度经营趋势</h2><div className="chart-placeholder"><div/><div/><div/><div/><div/><div/></div></section></>; }
export function EvaluationDetailPage() { const { id } = useParams(); return <><PageHeading title="评测用例详情" description={`用例 #${id} · 自然语言到 SQL 验证`} /><section className="card"><span className="eyebrow">业务问题</span><h2>近 30 天各区域充电收入与订单数趋势</h2><dl className="detail-list"><div><dt>执行状态</dt><dd><StatusBadge status="PUBLISHED" /></dd></div><div><dt>SQL 执行</dt><dd>通过</dd></div><div><dt>结果校验</dt><dd>业务签名一致</dd></div></dl><details><summary>查看 SQL 依据</summary><pre>SELECT region, SUM(amount), COUNT(*) FROM charging_orders GROUP BY region</pre></details></section></>; }
