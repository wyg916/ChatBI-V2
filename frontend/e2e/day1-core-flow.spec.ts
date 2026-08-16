import { expect, test, type APIRequestContext } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

async function list<T>(request: APIRequestContext, path: string): Promise<T[]> {
  const response = await request.get(`${apiBase}${path}`);
  expect(response.ok(), `GET ${path}`).toBeTruthy();
  const body = await response.json();
  return Array.isArray(body) ? body : body.items;
}

test('Day 1 数据源到语义模型核心流程', async ({ page, request }) => {
  const sources = await list<Record<string, unknown>>(request, '/datasources');
  const datasource = sources.find((item) => item.type === 'postgresql');
  expect(datasource, '本地数据库初始化与 Backend seed 应创建 PostgreSQL 主数据源').toBeTruthy();
  const sourceId = String(datasource!.id);
  const testResponse = await request.post(`${apiBase}/datasources/${sourceId}/test`);
  expect(testResponse.ok(), '测试连接 HTTP').toBeTruthy(); expect((await testResponse.json()).success, '测试连接业务结果').toBe(true);
  const syncResponse = await request.post(`${apiBase}/datasources/${sourceId}/sync`);
  expect(syncResponse.ok(), '同步 Schema HTTP').toBeTruthy(); expect((await syncResponse.json()).success, '同步 Schema 业务结果').toBe(true);

  await page.goto('/'); await expect(page.getByRole('heading', { name: '今天想了解哪些业务数据？' })).toBeVisible();
  await page.getByRole('link', { name: /数据源/ }).click(); await expect(page.getByRole('heading', { name: '数据源', exact: true }).last()).toBeVisible();
  await page.goto(`/datasources/${sourceId}`); await expect(page.getByRole('heading', { name: 'Schema 与字段管理' })).toBeVisible();
  const table = page.getByTestId('schema-table').first(); await expect(table).toBeVisible(); await table.click(); await expect(page.getByTestId('column-table')).toBeVisible();

  const models = await list<Record<string, unknown>>(request, '/semantic-models');
  let model = models.find((item) => item.name === '新能源经营分析');
  if (!model) {
    const created = await request.post(`${apiBase}/semantic-models`, { data: { name: '新能源经营分析', description: 'Day 1 可运行演示语义模型', datasource_id: sourceId }});
    expect(created.ok(), '创建 Demo Semantic Model').toBeTruthy(); model = await created.json();
  }
  await page.goto('/semantic-models'); await expect(page.getByRole('heading', { name: '语义模型', exact: true }).last()).toBeVisible();
  await page.goto(`/semantic-models/${String(model.id)}`); await expect(page.getByRole('heading', { name: '模型编辑器' })).toBeVisible();
  await expect(page.getByText('实体配置')).toBeVisible();
});

test('14 个路由可访问且目标视口无页面级横向裁切', async ({ page, request }) => {
  const sources = await list<Record<string, unknown>>(request, '/datasources');
  const models = await list<Record<string, unknown>>(request, '/semantic-models');
  const sourceId = String(sources[0].id);
  const modelId = String(models[0].id);
  const routes = [
    '/login', '/', '/ask/results', '/datasources', `/datasources/${sourceId}`,
    '/semantic-models', `/semantic-models/${modelId}`, '/answers', '/dashboards',
    '/dashboards/day1-demo', '/evaluation', '/evaluation/day1-demo',
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
