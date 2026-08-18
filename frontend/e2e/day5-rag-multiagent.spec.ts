import { expect, request as requestFactory, test, type APIRequestContext } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
const roles = ['PlannerAgent', 'DataAnalystAgent', 'KnowledgeAgent', 'VerificationAgent', 'InsightAgent'];
const tools = ['QUERY_DATA', 'RETRIEVE_KNOWLEDGE', 'VERIFY_RESULT', 'VERIFY_CITATION', 'GENERATE_CHART', 'GENERATE_INSIGHT'];
const complexQuestions = [
  '综合分析全部收入并结合收入口径给出经营洞察',
  '综合分析利润并结合成本口径给出经营洞察',
  '综合分析订单量并说明有效订单口径',
  '综合分析各地区收入并解释区域经营维度',
  '综合分析月度收入趋势并说明同比环比时间窗口',
  '综合分析收入并说明 SQL Guard 与 Result Oracle 验证规则',
  '综合分析各产品收入并结合退款口径给出洞察',
  '综合分析各客户订单量并说明订单去重口径',
  '综合分析季度利润并解释利润与成本定义',
  '综合分析区域订单量并给出可验证结论与引用',
];

async function runtimeIds(request: APIRequestContext) {
  const sourcesResponse = await request.get(`${apiBase}/datasources`);
  expect(sourcesResponse.ok(), await sourcesResponse.text()).toBeTruthy();
  const sources = await sourcesResponse.json() as Array<{ id: string; type: string; schema: string | null }>;
  const datasource = sources.find((item) => item.type === 'postgresql' && item.schema === 'demo_business');
  expect(datasource).toBeTruthy();
  const modelsResponse = await request.get(`${apiBase}/semantic-models`);
  expect(modelsResponse.ok(), await modelsResponse.text()).toBeTruthy();
  const models = await modelsResponse.json() as Array<{ id: string; name: string; datasource_id: string; status: string }>;
  const model = models.find((item) => (
    item.datasource_id === datasource!.id
    && item.status === 'PUBLISHED'
    && item.name === '新能源经营分析'
  ));
  expect(model).toBeTruthy();
  return { datasourceId: datasource!.id, semanticModelId: model!.id };
}

test('Day5-1 live RAG bridge and bounded agent capabilities are on', async ({ request }) => {
  const response = await request.get(`${apiBase}/query-capabilities`);
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = await response.json();
  expect(body.controlled_rag).toMatchObject({ mode: 'on', live_bridge: true, workspace_identity_signed: true, fail_closed: true });
  expect(body.bounded_orchestration.mode).toBe('on');
  expect(body.bounded_orchestration.roles).toEqual(roles);
  expect(body.bounded_orchestration.tools).toEqual(tools);
  expect(body.bounded_orchestration.budgets).toEqual({ max_steps: 8, max_tool_calls: 12, max_replan: 2, max_agent_depth: 2, timeout_ms: 30000 });
});

for (const [index, question] of complexQuestions.entries()) {
  test(`Day5-Complex-${String(index + 1).padStart(2, '0')} real trace is complete and verified`, async ({ request }, testInfo) => {
    const ids = await runtimeIds(request);
    const response = await request.post(`${apiBase}/analysis`, {
      data: {
        question,
        route: 'COMPLEX_ANALYSIS',
        datasource_id: ids.datasourceId,
        semantic_model_id: ids.semanticModelId,
        idempotency_key: `day5-complex-${String(index + 1).padStart(2, '0')}-${testInfo.workerIndex}-${Date.now()}`,
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const body = await response.json();
    expect(body.status).toBe('SUCCEEDED');
    expect(body.route).toBe('COMPLEX_ANALYSIS');
    expect(body.fallback_used).toBe(false);
    expect(body.security).toEqual({
      AGENT_DIRECT_DB_ACCESS: 0,
      AGENT_SQL_GUARD_BYPASS: 0,
      AGENT_RESULT_ORACLE_BYPASS: 0,
      UNAUTHORIZED_TOOL_CALL: 0,
      CROSS_WORKSPACE_LEAK: 0,
    });
    const run = body.primary;
    expect(run.trace_complete).toBe(true);
    expect(run.tool_call_count).toBe(6);
    expect(run.replan_count).toBe(0);
    expect(run.max_depth_observed).toBe(1);
    expect(run.steps).toHaveLength(7);
    expect([...new Set(run.steps.map((item: { agent_role: string }) => item.agent_role))].sort()).toEqual([...roles].sort());
    expect(run.steps.filter((item: { tool_name?: string }) => item.tool_name).map((item: { tool_name: string }) => item.tool_name)).toEqual(tools);
    expect(run.data_evidence.execution.result_signature).toMatch(/^[a-f0-9]{64}$/);
    expect(run.knowledge_evidence.citations.length).toBeGreaterThan(0);
    expect(run.verification).toEqual({ result_verified: true, citation_verified: true });
    expect(run.answer.length).toBeGreaterThan(0);
    expect(run.performance.total_latency_ms).toBeLessThanOrEqual(30000);
    expect(run.performance.tool_latency_ms).toBeGreaterThanOrEqual(0);
  });
}

test('Day5-12 knowledge and hybrid routes publish only verified evidence', async ({ request }) => {
  const ids = await runtimeIds(request);
  for (const route of ['KNOWLEDGE_QUERY', 'HYBRID_ANALYSIS']) {
    const response = await request.post(`${apiBase}/analysis`, {
      data: {
        question: route === 'KNOWLEDGE_QUERY' ? '收入口径与退款处理规则' : '统计收入并解释收入口径',
        route,
        datasource_id: ids.datasourceId,
        semantic_model_id: ids.semanticModelId,
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const body = await response.json();
    expect(body.status).toBe('SUCCEEDED');
    expect(body.fallback_used).toBe(false);
    const knowledge = route === 'KNOWLEDGE_QUERY' ? body.primary : body.primary.knowledge;
    expect(knowledge.answer_guard).toBe('PASSED');
    expect(knowledge.citations.length).toBeGreaterThan(0);
  }
});

test('Day5-13 SSE exposes finite stages and no reasoning payload', async ({ request }, testInfo) => {
  const ids = await runtimeIds(request);
  const response = await request.post(`${apiBase}/analysis/stream`, {
    data: {
      question: '综合分析收入并结合收入口径给出洞察',
      route: 'COMPLEX_ANALYSIS',
      datasource_id: ids.datasourceId,
      semantic_model_id: ids.semanticModelId,
      idempotency_key: `day5-stream-stage-${testInfo.workerIndex}-${Date.now()}`,
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const text = await response.text();
  const stages = [...text.matchAll(/"stage":\s*"([A-Z_]+)"/g)].map((item) => item[1]);
  expect(stages).toEqual(expect.arrayContaining(['UNDERSTANDING', 'QUERYING_DATA', 'RETRIEVING_KNOWLEDGE', 'VERIFYING', 'GENERATING_INSIGHT', 'COMPLETED']));
  expect(text.toLowerCase()).not.toContain('chain_of_thought');
  expect(text.toLowerCase()).not.toContain('reasoning');
});

test('Day5-14 missing session cannot access RAG or tools', async () => {
  const anonymous = await requestFactory.newContext({ storageState: { cookies: [], origins: [] } });
  const response = await anonymous.post(`${apiBase}/analysis`, {
    headers: { 'X-ChatBI-Actor': 'cross-workspace@chatbi.invalid' },
    data: { question: '收入口径', route: 'KNOWLEDGE_QUERY' },
  });
  expect(response.status()).toBe(401);
  expect(await response.text()).not.toContain('citations');
  await anonymous.dispose();
});

test('Day5-15 RAG no-evidence path explicitly falls back to verified data', async ({ request }) => {
  const ids = await runtimeIds(request);
  const response = await request.post(`${apiBase}/analysis`, {
    data: {
      question: '火星仓储无人机折旧政策',
      route: 'KNOWLEDGE_QUERY',
      datasource_id: ids.datasourceId,
      semantic_model_id: ids.semanticModelId,
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = await response.json();
  expect(body.status).toBe('SUCCEEDED');
  expect(body.fallback_used).toBe(true);
  expect(body.primary.oracle.status).toBe('PASSED');
  expect(body.shadow).toMatchObject({
    status: 'REFUSED',
    refusal_reason: 'NO_AUTHORIZED_EVIDENCE',
    citations: [],
  });
});
