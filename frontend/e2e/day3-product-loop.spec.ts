import { expect, test, type APIRequestContext, type APIResponse, type Page } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
const dashboardCardTitle = 'Day3 E2E 已验证卡片';

type JsonRecord = Record<string, any>;

async function json(response: APIResponse): Promise<JsonRecord> {
  expect(response.ok(), `${response.status()} ${response.url()}\n${await response.text()}`).toBeTruthy();
  return response.json();
}

async function ask(request: APIRequestContext, question: string, extra: JsonRecord = {}) {
  return json(await request.post(`${apiBase}/ask`, { data: { question, row_limit: 500, ...extra } }));
}

async function list(request: APIRequestContext, path: string) {
  const payload = await json(await request.get(`${apiBase}${path}`));
  return Array.isArray(payload) ? payload : payload.items;
}

function runtimeErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`));
  page.on('requestfailed', (request) => errors.push(`request: ${request.url()} ${request.failure()?.errorText ?? ''}`));
  page.on('response', (response) => { if (response.status() >= 400) errors.push(`response: ${response.status()} ${response.url()}`); });
  return errors;
}

test('Day3-E2E01 登录进入问数据首页', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('账号或电子名').fill('day3.user');
  await page.getByRole('button', { name: '登录 ChatBI Studio' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('heading', { name: '今天想了解哪些业务数据？' })).toBeVisible();
});

test('Day3-E2E02 PostgreSQL 数据源连接并同步 Schema', async ({ request }) => {
  const sources = await list(request, '/datasources');
  const postgres = sources.find((item: JsonRecord) => item.type === 'postgresql');
  expect(postgres).toBeTruthy();
  expect((await json(await request.post(`${apiBase}/datasources/${postgres.id}/test`))).success).toBe(true);
  const synced = await json(await request.post(`${apiBase}/datasources/${postgres.id}/sync`));
  expect(synced.success).toBe(true);
  const schemas = await list(request, `/datasources/${postgres.id}/schemas`);
  expect(schemas.length).toBeGreaterThan(0);
});

test('Day3-E2E03 语义模型指标维度可用并正式发布', async ({ request }) => {
  const sources = await list(request, '/datasources');
  const postgres = sources.find((item: JsonRecord) => item.type === 'postgresql');
  const models = await list(request, '/semantic-models');
  const model = models.find((item: JsonRecord) => item.datasource_id === postgres.id);
  expect(model).toBeTruthy();
  const detail = await json(await request.get(`${apiBase}/semantic-models/${model.id}`));
  expect(detail.metrics.length).toBeGreaterThan(0);
  expect(detail.dimensions.length).toBeGreaterThan(0);
  const published = await json(await request.put(`${apiBase}/semantic-models/${model.id}`, { data: { status: 'PUBLISHED' } }));
  expect(published.status).toBe('PUBLISHED');
});

test('Day3-E2E04 自然语言问题生成受语义约束的 SQLPlan', async ({ request }) => {
  const result = await ask(request, '统计全部订单收入');
  expect(result.status).toBe('SUCCEEDED');
  expect(result.context.candidate_tables.length).toBeGreaterThan(0);
  expect(result.plan.metrics).toContain('revenue');
  expect(result.plan.generated_sql).toContain('SUM');
});

test('Day3-E2E05 SQL Guard、只读执行与 Result Oracle 全部通过', async ({ request }) => {
  const result = await ask(request, '统计全部订单收入');
  expect(result.guard.allowed).toBe(true);
  expect(result.execution.status).toBe('SUCCEEDED');
  expect(result.oracle.status).toBe('PASSED');
  expect(result.execution.result_signature).toMatch(/^[a-f0-9]{64}$/);
});

test('Day3 ChartSpec 由查询结构生成并绑定结果证据', async ({ request }) => {
  const result = await ask(request, '2026年按月统计已支付订单收入趋势');
  expect(result.chart_spec.chart_type).toBe('LINE');
  expect(result.chart_spec.x_field).toBe('month');
  expect(result.chart_spec.y_fields).toContain('revenue');
  expect(result.chart_spec.data_source_query_id).toBe(result.id);
  expect(result.chart_spec.result_signature).toBe(result.execution.result_signature);
  expect(result.chart_spec.bound_row_count).toBe(result.execution.row_count);
});

test('Day3 Narrative 与推荐追问只引用当前结果', async ({ request }) => {
  const result = await ask(request, '按地区统计订单收入');
  expect(result.narrative.source_query_id).toBe(result.id);
  expect(result.narrative.result_signature).toBe(result.execution.result_signature);
  expect(result.narrative.semantic_model_version).toBe(result.semantic_model_version);
  expect(result.narrative.evidence.length).toBeGreaterThan(0);
  expect(result.recommended_questions.length).toBeGreaterThanOrEqual(3);
  expect(result.recommended_questions.length).toBeLessThanOrEqual(5);
});

test('Day3-E2E06 正确结果展示 KPI、Chart 与 Insight', async ({ page }) => {
  const errors = runtimeErrors(page);
  await page.goto(`/ask/results?q=${encodeURIComponent('按地区统计订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  const selectors = ['.analysis-answer-header', '.analysis-kpi-grid', '.analysis-chart-card', '.analysis-insight', '.query-inline-table', '.followup-suggestions'];
  const tops = await Promise.all(selectors.map((selector) => page.locator(selector).boundingBox().then((box) => box?.y ?? -1)));
  expect(tops).toEqual([...tops].sort((left, right) => left - right));
  await expect(page.getByRole('img', { name: '真实查询结果图表' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('Day3-E2E07 查询明细与依据展示完整证据链', async ({ page }) => {
  await page.goto(`/ask/results?q=${encodeURIComponent('统计全部订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await page.locator('.query-evidence-inline').getByText('查询依据').click();
  await expect(page.locator('.query-evidence-inline')).toContainText('Semantic Model Version');
  await expect(page.locator('.query-evidence-inline')).toContainText('Result Signature');
  await page.getByRole('button', { name: '查看 SQL 与执行明细' }).click();
  const dialog = page.getByRole('dialog', { name: 'SQL 与执行明细' });
  await expect(dialog).toContainText('Metric / Dimension');
  await expect(dialog).toContainText('Result Oracle');
  await expect(dialog).toContainText('SUM');
});

test('Day3-E2E08 推荐追问进入新一轮真实查询', async ({ page }) => {
  await page.goto(`/ask/results?q=${encodeURIComponent('统计全部订单收入')}`);
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  const suggestion = page.locator('.followup-suggestions button').first();
  const question = await suggestion.textContent();
  await suggestion.click();
  await expect(page).toHaveURL(new RegExp(`q=${encodeURIComponent(question ?? '').replace(/%/g, '%')}`));
  await expect(page.getByTestId('query-success')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.answer-query')).toHaveText(question ?? '');
});

test('Day3-E2E09 正确答案经反馈后保存为 VERIFIED Answer', async ({ request }) => {
  const result = await ask(request, '按产品统计订单收入前5名');
  const feedback = await json(await request.post(`${apiBase}/queries/${result.id}/feedback`, { data: { feedback_type: 'HELPFUL', comment: 'Day3 E2E' } }));
  expect(feedback.recorded).toBe(true);
  const answer = await json(await request.post(`${apiBase}/queries/${result.id}/save`, { data: { owner_name: 'Day3 E2E', status: 'VERIFIED' } }));
  expect(answer.status).toBe('VERIFIED');
  expect(answer.query_run_id).toBe(result.id);
  expect(answer.oracle_status).toBe('PASSED');
  expect(answer.chart_spec.data_source_query_id).toBe(result.id);
  const detail = await json(await request.get(`${apiBase}/answers/${answer.id}`));
  expect(detail.versions.length).toBeGreaterThanOrEqual(1);
});

test('Day3 已验证答案可复用且产生新 QueryRun', async ({ request }) => {
  const answers = await list(request, '/answers?tab=verified&page_size=100');
  const answer = answers.find((item: JsonRecord) => item.query_run_id && item.oracle_status === 'PASSED');
  expect(answer).toBeTruthy();
  const reused = await json(await request.post(`${apiBase}/answers/${answer.id}/reuse`));
  expect(reused.status).toBe('SUCCEEDED');
  expect(reused.id).not.toBe(answer.query_run_id);
  expect(reused.execution.result_signature).toBe(answer.result_signature);
});

test('Day3-E2E10 VERIFIED Answer 保存为 Dashboard Card', async ({ page, request }) => {
  const answers = await list(request, '/answers?tab=verified&page_size=100');
  const answer = answers.find((item: JsonRecord) => item.query_run_id && item.oracle_status === 'PASSED');
  const dashboards = await list(request, '/dashboards?page_size=100');
  expect(answer).toBeTruthy();
  expect(dashboards.length).toBeGreaterThan(0);
  const dashboardId = dashboards[0].id;
  const before = await json(await request.get(`${apiBase}/dashboards/${dashboardId}`));
  for (const existing of before.cards.filter((item: JsonRecord) => item.title === dashboardCardTitle)) {
    expect((await request.delete(`${apiBase}/dashboards/${dashboardId}/cards/${existing.id}`)).status()).toBe(204);
  }
  const card = await json(await request.post(`${apiBase}/dashboards/${dashboardId}/cards`, { data: { answer_id: answer.id, title: dashboardCardTitle } }));
  expect(card.result_signature).toBe(answer.result_signature);
  await page.goto(`/dashboards/${dashboardId}`);
  const cardUi = page.getByTestId('dashboard-answer-card').filter({ hasText: dashboardCardTitle });
  await expect(cardUi).toBeVisible({ timeout: 30_000 });
});

test('Day3-E2E11 Dashboard 查看来源并刷新真实数据', async ({ page, request }) => {
  const dashboards = await list(request, '/dashboards?page_size=100');
  const dashboardId = dashboards[0].id;
  const detail = await json(await request.get(`${apiBase}/dashboards/${dashboardId}`));
  const card = detail.cards.find((item: JsonRecord) => item.title === dashboardCardTitle);
  expect(card).toBeTruthy();
  const refreshed = await json(await request.post(`${apiBase}/dashboards/${dashboardId}/cards/${card.id}/refresh`));
  expect(refreshed.query_run_id).not.toBe(card.query_run_id);
  await page.goto(`/dashboards/${dashboardId}`);
  const cardUi = page.getByTestId('dashboard-answer-card').filter({ hasText: dashboardCardTitle });
  await expect(cardUi).toContainText('来源问题');
  await expect(cardUi.getByRole('button', { name: '查看来源问题' })).toBeVisible();
  expect((await request.delete(`${apiBase}/dashboards/${dashboardId}/cards/${card.id}`)).status()).toBe(204);
});

test('Day3-E2E12 Evaluation Center 真正运行并持久化 Golden20', async ({ request }) => {
  const triggered = await json(await request.post(`${apiBase}/evaluation/runs`));
  expect(triggered.run.status).toBe('PASS');
  const overview = await json(await request.get(`${apiBase}/evaluation/overview`));
  expect(overview.current.status).toBe('PASS');
  expect(overview.current.golden_set_count).toBe(20);
  expect(overview.current.sql_execution_pass_count).toBe(20);
  expect(overview.current.result_value_pass_count).toBe(20);
  expect(overview.current.dangerous_sql_block_count).toBe(overview.current.dangerous_sql_total);
  const detail = await json(await request.get(`${apiBase}/evaluation/runs/${overview.current.id}`));
  expect(detail.cases).toHaveLength(20);
  expect(detail.cases.every((item: JsonRecord) => item.status === 'PASS')).toBe(true);
});

test('Day3-E2E13 评测用例详情展示 Expected、Actual、SQL 与 ResultDiff', async ({ page, request }) => {
  const detail = await json(await request.get(`${apiBase}/evaluation/cases/G01`));
  expect(detail.case.status).toBe('PASS');
  expect(detail.case.expected.sql).toBeTruthy();
  expect(detail.case.generated_sql).toBeTruthy();
  await page.goto('/evaluation/G01');
  await expect(page.getByRole('heading', { name: '评测用例详情' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Expected', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Actual', exact: true })).toBeVisible();
  await expect(page.locator('.evaluation-metric').filter({ hasText: 'Result Diff' })).toContainText('0');
});

test('Day3-E2E14 危险 SQL 被拒绝且执行载荷为空', async ({ request }) => {
  for (const sql of ['DROP TABLE demo_business.orders', 'UPDATE demo_business.orders SET amount = 0', 'SELECT 1; SELECT 2']) {
    const result = await ask(request, sql);
    expect(result.status).toBe('SECURITY_REJECTED');
    expect(result.execution).toEqual({});
  }
});

test('Day3-E2E15 零行查询进入真实空状态', async ({ page, request }) => {
  const question = 'SELECT order_id FROM demo_business.orders WHERE 1 = 0';
  const result = await ask(request, question);
  expect(result.status).toBe('SUCCEEDED');
  expect(result.execution.row_count).toBe(0);
  await page.goto(`/ask/results?q=${encodeURIComponent(question)}`);
  await expect(page.getByTestId('query-empty')).toContainText('暂无匹配数据');
});

test('Day3 核心闭环页面三视口无裁切和运行时错误', async ({ page }) => {
  const errors = runtimeErrors(page);
  for (const viewport of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    for (const path of [`/ask/results?q=${encodeURIComponent('按地区统计订单收入')}`, '/answers', '/dashboards', '/evaluation', '/evaluation/G01']) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.locator('body')).toBeVisible();
      expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth + 1), `${path} @ ${viewport.width}x${viewport.height}`).toBe(true);
    }
  }
  expect(errors).toEqual([]);
});
