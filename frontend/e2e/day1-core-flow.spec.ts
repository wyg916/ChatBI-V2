import { expect, test, type APIRequestContext } from '@playwright/test';
import { adminCredentials } from './auth';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

async function list<T>(request: APIRequestContext, path: string): Promise<T[]> {
  const response = await request.get(`${apiBase}${path}`);
  expect(response.ok(), `GET ${path}`).toBeTruthy();
  const body = await response.json();
  return Array.isArray(body) ? body : body.items;
}

test('登录页表单进入默认问数据首页', async ({ page }) => {
  await page.context().clearCookies();
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
  await page.getByLabel('账号或电子名').fill(adminCredentials.email);
  await page.getByLabel('密码').fill(adminCredentials.password);
  await page.getByLabel('记住登录').uncheck();
  await page.getByRole('button', { name: '登录 ChatBI Studio' }).click();

  await expect(page).toHaveURL('/');
  await expect(page.getByRole('textbox', { name: '输入业务问题' })).toBeVisible();
});

test('Day 1 数据源到语义模型核心流程', async ({ page, request }) => {
  const sources = await list<Record<string, unknown>>(request, '/datasources');
  const datasource = sources.find((item) => item.type === 'postgresql');
  expect(datasource, '本地数据库初始化与 Backend seed 应创建 PostgreSQL 主数据源').toBeTruthy();
  const sourceId = String(datasource!.id);
  const testResponse = await request.post(`${apiBase}/datasources/${sourceId}/test`);
  expect(testResponse.ok(), '测试连接 HTTP').toBeTruthy(); expect((await testResponse.json()).success, '测试连接业务结果').toBe(true);
  const synchronizedSchemas = await list<Record<string, unknown>>(request, `/datasources/${sourceId}/schemas`);
  expect(synchronizedSchemas.length, '并行 worker 启动前应已完成隔离的 Schema fixture 同步').toBeGreaterThan(0);

  await page.goto('/?new=1'); await expect(page.getByRole('heading', { name: '今天想了解哪些业务数据？' })).toBeVisible();
  await page.getByRole('link', { name: /数据源/ }).click(); await expect(page.getByRole('heading', { name: '数据源', exact: true }).last()).toBeVisible();
  await page.goto(`/datasources/${sourceId}`); await expect(page.getByRole('heading', { name: 'Schema 与字段管理' })).toBeVisible();
  const table = page.getByTestId('schema-table').first(); await expect(table).toBeVisible(); await table.click(); await expect(page.getByTestId('column-table')).toBeVisible();

  const models = await list<Record<string, unknown>>(request, '/semantic-models');
  const model = models.find((item) => item.name === '新能源经营分析');
  expect(model, 'worker 前 fixture 应提供只读演示语义模型').toBeTruthy();
  await page.goto('/semantic-models'); await expect(page.getByRole('heading', { name: '语义模型', exact: true }).last()).toBeVisible();
  await page.goto(`/semantic-models/${String(model!.id)}`); await expect(page.getByRole('heading', { name: '模型编辑器' })).toBeVisible();
  await expect(page.getByText('实体配置')).toBeVisible();
});

test('14 个路由可访问且目标视口无页面级横向裁切', async ({ page, request }) => {
  const sources = await list<Record<string, unknown>>(request, '/datasources');
  const models = await list<Record<string, unknown>>(request, '/semantic-models');
  const dashboards = await list<Record<string, unknown>>(request, '/dashboards');
  const sourceId = String(sources[0].id);
  const modelId = String(models.find((item) => item.name === '新能源经营分析')!.id);
  const dashboardId = String(dashboards[0].id);
  const routes = [
    '/login', '/', '/ask/results', '/datasources', `/datasources/${sourceId}`,
    '/semantic-models', `/semantic-models/${modelId}`, '/answers', '/dashboards',
    `/dashboards/${dashboardId}`, '/evaluation', '/evaluation/G01',
    '/settings/models', '/settings/security',
  ];

  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    for (const route of routes) {
      await page.goto(route);
      await expect(page.locator('body')).toBeVisible();
      expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `${route} @ ${viewport.width}x${viewport.height}`).toBe(true);
    }
  }
});

test('语义模型列表与编辑器在目标视口无控制台、页面或阻断请求错误', async ({ page, request }) => {
  const models = await list<Record<string, unknown>>(request, '/semantic-models');
  const modelId = String(models.find((item) => item.name === '新能源经营分析')!.id);
  const runtimeErrors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') runtimeErrors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => runtimeErrors.push(`page: ${error.message}`));
  page.on('requestfailed', (failed) => runtimeErrors.push(`request: ${failed.url()} ${failed.failure()?.errorText ?? ''}`));

  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/semantic-models');
    await expect(page.getByTestId('semantic-model-card').first()).toBeVisible();
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `list @ ${viewport.width}x${viewport.height}`).toBe(true);

    await page.goto(`/semantic-models/${modelId}`);
    await expect(page.getByRole('heading', { name: '模型编辑器' })).toBeVisible();
    await expect(page.locator('.semantic-node').first()).toBeVisible();
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `editor @ ${viewport.width}x${viewport.height}`).toBe(true);
  }

  expect(runtimeErrors).toEqual([]);
});

test('内容中心、经营看板详情与评测总览由 API 驱动并适配三个目标视口', async ({ page, request }) => {
  const answerResponse = await request.get(`${apiBase}/answers`);
  const dashboardResponse = await request.get(`${apiBase}/dashboards`);
  const evaluationResponse = await request.get(`${apiBase}/evaluation/overview`);
  expect(answerResponse.ok(), '答案库 API').toBeTruthy();
  expect(dashboardResponse.ok(), '看板 API').toBeTruthy();
  expect(evaluationResponse.ok(), '评测中心 API').toBeTruthy();
  expect((await answerResponse.json()).summary.total).toBeGreaterThanOrEqual(6);
  const dashboardPayload = await dashboardResponse.json();
  expect(dashboardPayload.summary.total).toBeGreaterThanOrEqual(6);

  const runtimeErrors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') runtimeErrors.push(`console: ${message.text()}`); });
  page.on('pageerror', (error) => runtimeErrors.push(`page: ${error.message}`));
  page.on('requestfailed', (failed) => runtimeErrors.push(`request: ${failed.url()} ${failed.failure()?.errorText ?? ''}`));

  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/answers');
    await expect(page.getByTestId('answer-row').first()).toBeVisible();
    await expect(page.getByText('平均推荐准确率')).toBeVisible();
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `answers @ ${viewport.width}x${viewport.height}`).toBe(true);

    await page.goto('/dashboards');
    await expect(page.getByTestId('dashboard-card').first()).toBeVisible();
    await expect(page.getByText('分析卡片')).toBeVisible();
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `dashboards @ ${viewport.width}x${viewport.height}`).toBe(true);

    await page.goto(`/dashboards/${String(dashboardPayload.items[0].id)}`);
    await expect(page.getByTestId('dashboard-detail')).toBeVisible();
    await expect(page.getByRole('heading', { name: '收入趋势' })).toBeVisible();
    await expect(page.getByRole('img', { name: '收入趋势' })).toBeVisible();
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `dashboard detail @ ${viewport.width}x${viewport.height}`).toBe(true);

    await page.goto('/evaluation');
    // The overview aggregates real evaluation history and can exceed the
    // default UI assertion timeout on a cold or resource-contended database.
    await expect(page.getByTestId('evaluation-overview')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('最近评测运行')).toBeVisible();
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth), `evaluation @ ${viewport.width}x${viewport.height}`).toBe(true);
  }

  expect(runtimeErrors).toEqual([]);
});
