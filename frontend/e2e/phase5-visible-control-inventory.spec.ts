import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
const outputPath = resolve(
  process.env.CHATBI_PHASE5_CONTROL_EVIDENCE
    ?? 'test-results/phase5-visible-control-inventory.json',
);

type Resource = { id: string; name?: string };
type PageTarget = { page: string; route: string };
type ControlRecord = {
  page: string;
  route: string;
  control_id: string;
  control_text: string;
  control_type: string;
  tag: string;
  role: string;
  test_id: string | null;
  visible_state: 'VISIBLE';
  enabled_state: 'ENABLED' | 'DISABLED';
  required_role: 'ADMIN';
  action: string;
  expected_result: string;
  backend_api: 'NOT_YET_MAPPED';
  database_effect: 'NOT_YET_MAPPED';
  persistence_required: 'NOT_YET_MAPPED';
  current_status: 'INVENTORIED_NOT_FUNCTIONALLY_CERTIFIED';
  surface: string;
};

async function list(request: APIRequestContext, path: string): Promise<Resource[]> {
  const response = await request.get(`${apiBase}${path}`);
  expect(response.ok(), `GET ${path}`).toBeTruthy();
  const payload = await response.json();
  return Array.isArray(payload) ? payload : payload.items;
}

async function targets(request: APIRequestContext): Promise<PageTarget[]> {
  const [sources, models, dashboards] = await Promise.all([
    list(request, '/datasources'),
    list(request, '/semantic-models'),
    list(request, '/dashboards'),
  ]);
  expect(sources.length, 'control inventory requires a datasource').toBeGreaterThan(0);
  expect(models.length, 'control inventory requires a semantic model').toBeGreaterThan(0);
  expect(dashboards.length, 'control inventory requires a dashboard').toBeGreaterThan(0);
  const primaryModel = models.find((item) => item.name === '新能源经营分析') ?? models[0];
  return [
    { page: '登录页', route: '/login' },
    { page: '问数据-会话状态', route: '/' },
    { page: '问数据-空状态', route: '/?new=1' },
    { page: '问数据-分析结果', route: `/ask/results?q=${encodeURIComponent('统计全部订单收入')}` },
    { page: '数据源列表', route: '/datasources' },
    { page: '数据源详情', route: `/datasources/${sources[0].id}` },
    { page: '数据工作台', route: `/datasources/${sources[0].id}/workspace` },
    { page: '语义模型列表', route: '/semantic-models' },
    { page: '语义模型编辑器', route: `/semantic-models/${primaryModel.id}` },
    { page: '答案库', route: '/answers' },
    { page: '看板列表', route: '/dashboards' },
    { page: '看板详情', route: `/dashboards/${dashboards[0].id}` },
    { page: '评测中心', route: '/evaluation' },
    { page: '评测反馈与Verified SQL', route: '/evaluation?view=feedback' },
    { page: '评测用例详情', route: '/evaluation/G01' },
    { page: '模型与成本设置', route: '/settings/models' },
    { page: '治理中心-成本与用量', route: '/settings/models?view=cost' },
    { page: '治理中心-ONE_TRACE', route: '/settings/models?view=trace' },
    { page: '治理中心-模型治理', route: '/settings/models?view=model' },
    { page: '治理中心-评测治理', route: '/settings/models?view=evaluation' },
    { page: '用户角色与审计', route: '/settings/security' },
  ];
}

const selector = [
  'button', 'a[href]', 'input:not([type="hidden"])', 'textarea', 'select',
  '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
  '[role="switch"]', '[role="checkbox"]', '[role="radio"]', '[contenteditable="true"]',
].join(',');

async function scan(page: Page, target: PageTarget, surface: string): Promise<ControlRecord[]> {
  const raw = await page.locator(selector).evaluateAll((elements) => elements.flatMap((element, index) => {
    const node = element as HTMLElement;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    if (
      style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0
      || rect.width <= 0 || rect.height <= 0
    ) return [];
    const input = node as HTMLInputElement;
    const tag = node.tagName.toLowerCase();
    const role = node.getAttribute('role') ?? '';
    const type = input.type ?? '';
    const text = (
      node.getAttribute('aria-label')
      || node.getAttribute('title')
      || node.textContent
      || input.placeholder
      || input.value
      || ''
    ).replace(/\s+/g, ' ').trim().slice(0, 240);
    const disabled = input.disabled || node.getAttribute('aria-disabled') === 'true';
    let controlType = 'BUTTON';
    if (tag === 'a' || role === 'link') controlType = 'LINK_ACTION';
    else if (role === 'tab') controlType = 'TAB';
    else if (role === 'menuitem') controlType = 'MENU_ITEM';
    else if (tag === 'select') controlType = 'DROPDOWN_ACTION';
    else if (type === 'file') controlType = 'UPLOAD';
    else if (type === 'checkbox' || role === 'checkbox') controlType = 'CHECKBOX';
    else if (role === 'switch') controlType = 'TOGGLE';
    else if (type === 'radio' || role === 'radio') controlType = 'RADIO';
    else if (tag === 'input' || tag === 'textarea' || node.isContentEditable) controlType = 'INPUT';
    else if (role === 'button' && !['button', 'input'].includes(tag)) controlType = 'ICON_BUTTON';
    return [{ index, tag, role, type, text, disabled, controlType, testId: node.dataset.testid ?? null }];
  }));

  return raw.map((item) => {
    const identity = `${target.route}|${surface}|${item.index}|${item.tag}|${item.role}|${item.text}`;
    const controlId = `CTL-${createHash('sha256').update(identity).digest('hex').slice(0, 16)}`;
    const action = item.controlType === 'INPUT' ? 'ENTER_VALUE'
      : item.controlType === 'DROPDOWN_ACTION' ? 'SELECT_OPTION'
        : item.controlType === 'UPLOAD' ? 'UPLOAD_FILE'
          : item.controlType === 'CHECKBOX' || item.controlType === 'RADIO' || item.controlType === 'TOGGLE'
            ? 'TOGGLE_STATE' : 'CLICK';
    return {
      page: target.page,
      route: target.route,
      control_id: controlId,
      control_text: item.text || `[${item.controlType.toLowerCase()}-${item.index}]`,
      control_type: item.controlType,
      tag: item.tag,
      role: item.role,
      test_id: item.testId,
      visible_state: 'VISIBLE',
      enabled_state: item.disabled ? 'DISABLED' : 'ENABLED',
      required_role: 'ADMIN',
      action,
      expected_result: 'REQUIRES_CONTROL_SPECIFIC_ACCEPTANCE_MAPPING',
      backend_api: 'NOT_YET_MAPPED',
      database_effect: 'NOT_YET_MAPPED',
      persistence_required: 'NOT_YET_MAPPED',
      current_status: 'INVENTORIED_NOT_FUNCTIONALLY_CERTIFIED',
      surface,
    } satisfies ControlRecord;
  });
}

test('Phase5 real-browser visible control inventory', async ({ page, request }) => {
  test.setTimeout(300_000);
  const inventory: ControlRecord[] = [];
  const pageRows: Array<{ page: string; route: string; visible_controls: number; enabled_controls: number }> = [];
  for (const target of await targets(request)) {
    const response = await page.goto(target.route);
    expect(response?.status(), `${target.page} direct navigation`).toBe(200);
    await page.waitForLoadState('networkidle');
    const actualPath = new URL(page.url()).pathname;
    if (target.route === '/login') {
      expect(actualPath, 'login inventory must remain on the public login page').toBe('/login');
    } else {
      expect(actualPath, `${target.page} must be authenticated instead of redirecting to login`).not.toBe('/login');
    }
    const rows = await scan(page, target, 'BASE_PAGE');
    inventory.push(...rows);
    pageRows.push({
      page: target.page,
      route: target.route,
      visible_controls: rows.length,
      enabled_controls: rows.filter((item) => item.enabled_state === 'ENABLED').length,
    });
  }
  const serializedInventory = JSON.stringify(inventory);
  const payload = {
    schema_version: 'chatbi.v13.phase5.visible-control-inventory.v1',
    status: 'INVENTORY_COMPLETE_ACCEPTANCE_NOT_CERTIFIED',
    generated_at: new Date().toISOString(),
    browser: 'chromium',
    viewport: { width: 1440, height: 900 },
    role: 'ADMIN',
    page_count: pageRows.length,
    total_visible_controls: inventory.length,
    total_actionable_controls: inventory.filter((item) => item.enabled_state === 'ENABLED').length,
    total_tested_controls: 0,
    visible_actionable_control_coverage: 0,
    applicable_control_pass_rate: null,
    noop_control_count: null,
    broken_control_count: null,
    fake_success_count: null,
    paid_provider_calls: 0,
    acceptance_note: 'Inventory is not functional acceptance; each enabled control still requires Browser-API-DB-readback-refresh evidence.',
    pages: pageRows,
    inventory_sha256: createHash('sha256').update(serializedInventory).digest('hex'),
    controls: inventory,
  };
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  expect(pageRows).toHaveLength(21);
  expect(inventory.length).toBeGreaterThan(0);
});
