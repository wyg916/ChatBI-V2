import { useNavigate } from 'react-router-dom';

const prompts = [
  ['销', '本月销售额是多少？', '收入、订单数、毛利等关键指标'],
  ['区', '哪些区域收入下降最明显？', '区域对比、趋势变化分析'],
  ['客', '近30天新增会员有多少？', '会员增长、来源及转化率分析'],
  ['存', '最近7天库存情况如何？', '库存、周转及备货建议分析'],
];

export function AskPage({ results = false }: { results?: boolean }) {
  const navigate = useNavigate();
  if (results) return <div className="result-page"><div className="answer-query">分析今年各月份的成交额与毛利趋势</div><section className="answer-card"><span className="eyebrow">一句话结论</span><h1>今年成交额整体稳步增长，六月环比提升 12.4%</h1><div className="kpi-row"><article><small>累计成交额</small><strong>¥ 2,486 万</strong><em>↑ 18.6%</em></article><article><small>订单数量</small><strong>48,216</strong><em>↑ 9.2%</em></article><article><small>综合毛利率</small><strong>27.8%</strong><em>↑ 2.1pp</em></article></div><div className="chart-placeholder"><div/><div/><div/><div/><div/><div/><span>1月　 2月　 3月　 4月　 5月　 6月</span></div><h3>业务洞察</h3><p>华东与华南区域贡献了本期增长的 71%，建议继续关注高价值客户的复购表现。</p><details><summary>查看可核验的查询依据</summary><code>SELECT month, SUM(amount) FROM orders GROUP BY month</code></details></section></div>;
  return <div className="ask-empty"><div className="hero-mark">BI</div><h1>今天想了解哪些业务数据？</h1><p>直接用自然语言提问，系统会基于已发布的语义模型生成可核验的数据分析。</p><div className="ask-box"><textarea aria-label="输入业务问题" placeholder="例如：分析今年各月份的成交额、客单价趋势，并找出下降最明显的三个区域。"/><div><span className="chip">深度分析报告</span><span className="chip">选择语义模型</span><button className="ask-submit" aria-label="提交问题" onClick={() => navigate('/ask/results')}>→</button></div></div><div className="prompt-section"><span>猜你想问</span><div className="prompt-grid">{prompts.map(([icon, title, sub]) => <button key={title} onClick={() => navigate('/ask/results')}><b>{icon}</b><span><strong>{title}</strong><small>{sub}</small></span></button>)}</div></div></div>;
}
