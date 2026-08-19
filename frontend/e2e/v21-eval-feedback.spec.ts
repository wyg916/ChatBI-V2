import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test';
import { captureRuntimeErrors } from './runtime-errors';


const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

async function json(response: APIResponse) {
  expect(response.ok(), `${response.status()} ${response.url()}\n${await response.text()}`).toBeTruthy();
  return response.json();
}

async function runtime(request: APIRequestContext) {
  const sources = await json(await request.get(`${apiBase}/datasources`)) as Array<{ id: string; type: string; schema: string | null }>;
  const source = sources.find((item) => item.type === 'postgresql' && item.schema === 'demo_business');
  expect(source).toBeTruthy();
  const models = await json(await request.get(`${apiBase}/semantic-models`)) as Array<{ id: string; datasource_id: string; status: string }>;
  const model = models.find((item) => item.datasource_id === source!.id && item.status === 'PUBLISHED');
  expect(model).toBeTruthy();
  return { source: source!, model: model! };
}

test('V2.1-EVAL Evaluation 页面完成创建、执行、Dashboard、比较与 CI Gate', async ({ page, request }) => {
  test.setTimeout(240_000);
  const runtimeErrors = captureRuntimeErrors(page);
  const created = await json(await request.post(`${apiBase}/evaluation/definitions`, { data: {
    name: 'V2.1 Evaluation E2E',
    profile: { model: 'deterministic', prompt: 'e2e-prompt', semantic_engine: 'chatbi-semantic', nl2sql_engine: 'chatbi-nl2sql', version: 'e2e' },
  } }));
  expect(created.status).toBe('CREATED');
  const executed = await json(await request.post(`${apiBase}/evaluation/runs/${created.id}/execute`, { timeout: 220_000 }));
  expect(executed.run.golden_set_count).toBeGreaterThanOrEqual(50);
  expect(executed.run.multiple_ground_truth).toBe(true);
  expect(Object.keys(executed.run.accuracy)).toEqual(expect.arrayContaining(['metric', 'dimension', 'time', 'filter', 'join', 'result_value', 'chart', 'narrative']));
  const gate = await json(await request.get(`${apiBase}/evaluation/runs/${created.id}/gate`));
  expect(gate.status).toBe('PASS');
  const dashboard = await json(await request.get(`${apiBase}/evaluation/dashboard?run_id=${created.id}`));
  expect(dashboard.accuracy_cards).toHaveLength(8);
  expect(dashboard.comparison_axes).toEqual(['model', 'prompt', 'semantic_engine', 'nl2sql_engine', 'version']);
  const overview = await json(await request.get(`${apiBase}/evaluation/overview`));
  const comparisonPeer = overview.comparisons.find((item: { id: string; status: string }) => item.id !== created.id && ['PASS', 'FAIL'].includes(item.status));
  expect(comparisonPeer).toBeTruthy();
  const comparison = await json(await request.post(`${apiBase}/evaluation/compare`, { data: { run_ids: [created.id, comparisonPeer.id] } }));
  expect(comparison.axes).toEqual(['model', 'prompt', 'semantic_engine', 'nl2sql_engine', 'version']);
  expect(comparison.runs).toHaveLength(2);

  await page.goto('/evaluation');
  await expect(page.getByTestId('evaluation-overview')).toBeVisible();
  await expect(page.getByTestId('oracle-accuracy-grid').locator('article')).toHaveCount(8);
  await expect(page.getByText('CI Release Gate')).toBeVisible();
  expect(runtimeErrors).toEqual({ consoleErrors: [], pageErrors: [], blockingRequestErrors: [] });
});

test('V2.1-FEEDBACK Feedback 页面完成错误修正、审核、Verified SQL 召回和 Oracle 回放', async ({ page, request }) => {
  test.setTimeout(120_000);
  const runtimeErrors = captureRuntimeErrors(page);
  const { source, model } = await runtime(request);
  const question = '按地区统计订单收入';
  const asked = await json(await request.post(`${apiBase}/ask`, { data: {
    question,
    datasource_id: source.id,
    semantic_model_id: model.id,
    row_limit: 500,
  } }));
  expect(asked.status).toBe('SUCCEEDED');
  expect(asked.guard.allowed).toBe(true);
  expect(asked.oracle.status).toBe('PASSED');

  const correct = await json(await request.post(`${apiBase}/evaluation/feedback/correct`, { data: {
    query_run_id: asked.id,
    comment: 'E2E 正确反馈',
  } }));
  expect(correct.recorded).toBe(true);

  const correction = await json(await request.post(`${apiBase}/evaluation/feedback/incorrect`, { data: {
    query_run_id: asked.id,
    comment: 'E2E 人工修正',
    corrected_sql: asked.plan.generated_sql,
    expected_columns: asked.execution.columns,
    expected_rows: asked.execution.rows,
    owner_name: 'E2E Reviewer',
  } }));
  expect(correction.workflow_state).toBe('CORRECTION_SUBMITTED');
  expect(correction.oracle_status).toBe('PASSED');
  const reviewed = await json(await request.post(`${apiBase}/evaluation/feedback/${correction.answer_id}/review`, { data: {
    decision: 'APPROVE',
    comment: 'E2E 审核通过',
  } }));
  expect(reviewed.workflow_state).toBe('VERIFIED_SQL');
  expect(reviewed.version).toBe(2);

  const similarQuestion = '按区域统计订单营收';
  const recalled = await json(await request.post(`${apiBase}/evaluation/feedback/recall`, { data: { question: similarQuestion } }));
  expect(recalled.candidates.some((item: { answer_id: string }) => item.answer_id === correction.answer_id)).toBe(true);
  const replay = await json(await request.post(`${apiBase}/evaluation/feedback/${correction.answer_id}/replay`, { data: { question: similarQuestion } }));
  expect(replay.guard_status).toBe('PASS');
  expect(replay.oracle_status).toBe('PASSED');
  expect(replay.replay_passed).toBe(true);
  expect(replay.replay_rate).toBe(1);

  await page.goto('/evaluation?view=feedback');
  await expect(page.getByTestId('feedback-page')).toBeVisible();
  await expect(page.getByText('FEEDBACK_REPLAY_RATE')).toBeVisible();
  await expect(page.getByTestId('feedback-workflows')).toContainText('REGRESSION_PASS');
  expect(runtimeErrors).toEqual({ consoleErrors: [], pageErrors: [], blockingRequestErrors: [] });
});
