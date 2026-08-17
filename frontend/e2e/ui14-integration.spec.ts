import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

type PageTarget = {
  id: string;
  title: string;
  path: string;
  appShell: boolean;
  ready: (page: Page) => Locator;
  criticalControl: (page: Page) => Locator;
};

async function list<T>(request: APIRequestContext, path: string): Promise<T[]> {
  const response = await request.get(`${apiBase}${path}`);
  expect(response.ok(), `GET ${path}`).toBeTruthy();
  const body = await response.json();
  return Array.isArray(body) ? body : body.items;
}

function captureRuntimeErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`request: ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) errors.push(`response: ${response.status()} ${response.url()}`);
  });
  return errors;
}

async function pageTargets(request: APIRequestContext): Promise<PageTarget[]> {
  const [sources, models, dashboards] = await Promise.all([
    list<{ id: string }>(request, '/datasources'),
    list<{ id: string }>(request, '/semantic-models'),
    list<{ id: string }>(request, '/dashboards'),
  ]);
  expect(sources.length, 'UI14 requires a seeded datasource').toBeGreaterThan(0);
  expect(models.length, 'UI14 requires a seeded semantic model').toBeGreaterThan(0);
  expect(dashboards.length, 'UI14 requires a seeded dashboard').toBeGreaterThan(0);
  const primaryModel = models.find((item: any) => item.name === '新能源经营分析');
  expect(primaryModel, 'UI14 requires the stable PostgreSQL semantic model').toBeTruthy();

  return [
    { id: '01', title: '登录页', path: '/login', appShell: false, ready: (page) => page.getByRole('heading', { name: '登录工作空间' }), criticalControl: (page) => page.getByRole('button', { name: '登录 ChatBI Studio' }) },
    { id: '02', title: '问数据 - 空状态', path: '/?new=1', appShell: true, ready: (page) => page.getByRole('heading', { name: '今天想了解哪些业务数据？' }), criticalControl: (page) => page.getByRole('button', { name: '提交问题' }) },
    { id: '03', title: '问数据 - 分析结果', path: `/ask/results?q=${encodeURIComponent('统计全部订单收入')}`, appShell: true, ready: (page) => page.getByTestId('query-success'), criticalControl: (page) => page.getByRole('button', { name: '查看 SQL 与执行明细' }) },
    { id: '04', title: '数据源列表', path: '/datasources', appShell: true, ready: (page) => page.getByTestId('datasource-card').first(), criticalControl: (page) => page.getByTestId('create-datasource') },
    { id: '05', title: '数据源详情与 Schema 管理', path: `/datasources/${sources[0].id}`, appShell: true, ready: (page) => page.getByRole('heading', { name: 'Schema 与字段管理' }), criticalControl: (page) => page.getByTestId('sync-schema') },
    { id: '06', title: '语义模型列表', path: '/semantic-models', appShell: true, ready: (page) => page.getByTestId('semantic-model-card').first(), criticalControl: (page) => page.getByTestId('create-model') },
    { id: '07', title: '语义模型编辑器', path: `/semantic-models/${primaryModel!.id}`, appShell: true, ready: (page) => page.getByRole('heading', { name: '模型编辑器' }), criticalControl: (page) => page.getByTestId('save-model') },
    { id: '08', title: '答案库', path: '/answers', appShell: true, ready: (page) => page.getByTestId('answer-row').first(), criticalControl: (page) => page.getByRole('button', { name: '＋ 新建标准答案' }) },
    { id: '09', title: '看板列表', path: '/dashboards', appShell: true, ready: (page) => page.getByTestId('dashboard-card').first(), criticalControl: (page) => page.getByRole('button', { name: '＋ 新建看板' }) },
    { id: '10', title: '经营看板详情', path: `/dashboards/${dashboards[0].id}`, appShell: true, ready: (page) => page.getByTestId('dashboard-detail'), criticalControl: (page) => page.getByRole('button', { name: /刷新/ }) },
    { id: '11', title: '评测中心总览', path: '/evaluation', appShell: true, ready: (page) => page.getByTestId('evaluation-overview'), criticalControl: (page) => page.getByRole('button', { name: /运行 Golden 50/ }) },
    { id: '12', title: '评测用例详情', path: '/evaluation/G01', appShell: true, ready: (page) => page.getByRole('heading', { name: '评测用例详情' }), criticalControl: (page) => page.getByRole('button', { name: '重新运行' }) },
    { id: '13', title: '系统设置与模型服务', path: '/settings/models', appShell: true, ready: (page) => page.getByTestId('settings-models-page'), criticalControl: (page) => page.getByRole('button', { name: '保存全部设置' }) },
    { id: '14', title: '用户角色与审计', path: '/settings/security', appShell: true, ready: (page) => page.getByTestId('security-audit-page'), criticalControl: (page) => page.getByRole('button', { name: '＋ 邀请成员' }) },
  ];
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`UI14 三视口集成 Gate ${viewport.width}x${viewport.height}`, async ({ page, request }, testInfo) => {
    const errors = captureRuntimeErrors(page);
    const targets = await pageTargets(request);
    expect(targets).toHaveLength(14);
    await page.setViewportSize(viewport);

    for (const target of targets) {
      await test.step(`${target.id} ${target.title}`, async () => {
        const response = await page.goto(target.path);
        expect(response?.status(), `${target.title} direct URL response`).toBe(200);
        await expect(target.ready(page), `${target.title} ready marker`).toBeVisible({ timeout: 30_000 });
        await expect(page.locator('.notice.error'), `${target.title} API error notice`).toHaveCount(0);

        const primaryNav = page.getByRole('navigation', { name: '一级导航' });
        if (target.appShell) {
          await expect(primaryNav).toBeVisible();
          await expect(primaryNav.locator('a')).toHaveCount(6);
          await expect(primaryNav).not.toContainText('系统设置');
        } else {
          await expect(primaryNav).toHaveCount(0);
        }

        const layout = await page.evaluate(() => {
          const root = document.documentElement;
          const body = document.body;
          const main = document.querySelector('main') ?? body;
          const rect = main.getBoundingClientRect();
          return {
            documentWidth: Math.max(root.scrollWidth, body.scrollWidth),
            viewportWidth: window.innerWidth,
            mainLeft: rect.left,
            mainRight: rect.right,
          };
        });
        expect(layout.documentWidth, `${target.title} page-level horizontal clipping`).toBeLessThanOrEqual(layout.viewportWidth + 1);
        expect(layout.mainLeft, `${target.title} main content left bound`).toBeGreaterThanOrEqual(-1);
        expect(layout.mainRight, `${target.title} main content right bound`).toBeLessThanOrEqual(layout.viewportWidth + 1);

        const criticalControl = target.criticalControl(page).first();
        await expect(criticalControl, `${target.title} critical control`).toBeVisible();
        const controlGate = await criticalControl.evaluate((element) => {
          const rect = element.getBoundingClientRect();
          const centerX = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
          const centerY = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
          const topElement = document.elementFromPoint(centerX, centerY);
          return {
            withinViewport: rect.left >= -1 && rect.right <= window.innerWidth + 1 && rect.top >= -1 && rect.bottom <= window.innerHeight + 1,
            unobstructed: Boolean(topElement && (element.contains(topElement) || topElement.contains(element))),
          };
        });
        expect(controlGate.withinViewport, `${target.title} critical control clipped`).toBe(true);
        expect(controlGate.unobstructed, `${target.title} critical control obstructed`).toBe(true);

        const screenshotName = `page-${target.id}-${viewport.width}x${viewport.height}.png`;
        const screenshotPath = testInfo.outputPath(screenshotName);
        await page.screenshot({ path: screenshotPath, fullPage: false });
        await testInfo.attach(screenshotName, { path: screenshotPath, contentType: 'image/png' });
      });
    }

    expect(errors, `runtime errors @ ${viewport.width}x${viewport.height}`).toEqual([]);
  });
}
