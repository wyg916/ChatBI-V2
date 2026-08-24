import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
const outputPath = resolve(
  process.env.CHATBI_PHASE5_CONTROL_EVIDENCE
    ?? 'test-results/phase5-visible-control-inventory.json',
);

const CONTROL_INVENTORY_SCHEMA_VERSION = 'chatbi.v13.phase5.logical-control-inventory.v2';
const CONTROL_DISCOVERY_RULES = {
  schema_version: CONTROL_INVENTORY_SCHEMA_VERSION,
  visible: 'Computed display is not none, visibility is not hidden, opacity is non-zero, the bounding box is positive, and Playwright reports visible.',
  actionable: 'At least one visible DOM instance of the logical control is enabled and is not readonly or aria-disabled.',
  disabled: 'A visible logical control whose every visible DOM instance is disabled, readonly, or aria-disabled.',
  duplicate: 'Visible DOM instances with the same route, state surface, and declared or semantic logical key are one logical control.',
  responsive_clone: 'Desktop/mobile clones share one logical control; hidden clones are excluded and visible clones increment DOM_INSTANCE_COUNT.',
  hidden_dom: 'Display-none, visibility-hidden, opacity-zero, zero-area, and Playwright-hidden nodes are excluded from logical and actionable counts.',
  role_specific: 'Inventory is captured under the declared authenticated role; REQUIRED_ROLE records that role and role-specific surfaces remain separate.',
  state_specific: 'A control exposed only in a distinct activated surface uses that surface in its logical identity.',
  menu_item: 'A menu item is counted only when its menu surface is activated and visible; closed-menu DOM is hidden and excluded.',
  row_template: 'Repeated table-row instances with one declared data-logical-control are one logical control and increment DOM_INSTANCE_COUNT.',
  portal_modal_clone: 'A portal/modal shadow instance with the same route, state surface, and logical key is a clone, not a new logical control.',
  virtualized_row_control: 'Observed viewport rows contribute DOM instances; resource IDs never form LOGICAL_CONTROL_ID.',
  dynamic_resource: 'Dynamic rows declare data-logical-control, data-resource-type, and data-resource-id; only the first two affect logical identity.',
} as const;
const CONTROL_DISCOVERY_RULE_HASH = createHash('sha256')
  .update(JSON.stringify(CONTROL_DISCOVERY_RULES))
  .digest('hex');

type Resource = { id: string; name?: string; type?: string };
type PageTarget = { page: string; route: string };
type DomInstance = {
  selector_index: number;
  locator: string;
  control_text: string;
  enabled: boolean;
  resource_id: string | null;
};
type ControlRecord = {
  page: string;
  route: string;
  control_id: string;
  logical_control_id: string;
  logical_key: string;
  control_text: string;
  control_type: string;
  tag: string;
  role: string;
  test_id: string | null;
  selector_index: number;
  locator: string;
  href: string | null;
  aria_label: string | null;
  input_type: string | null;
  option_values: string[];
  identity_ordinal: 0;
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
  dom_instance_count: number;
  disabled_dom_instance_count: number;
  resource_type: string | null;
  resource_instance_count: number;
  dynamic_resource: boolean;
  clone_classification: 'NONE' | 'RESPONSIVE_OR_PORTAL_CLONE' | 'ROW_TEMPLATE_OR_VIRTUALIZED_RESOURCE_INSTANCES';
  dom_instances: DomInstance[];
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
  const primarySource = sources.find((item) => item.type === 'postgresql') ?? sources[0];
  const preferredModelName = process.env.CHATBI_CONTROL_MODEL_NAME;
  const preferredDashboardName = process.env.CHATBI_CONTROL_DASHBOARD_NAME;
  const primaryModel = models.find((item) => item.name === preferredModelName)
    ?? models.find((item) => item.name === '新能源经营分析')
    ?? models[0];
  const primaryDashboard = dashboards.find((item) => item.name === preferredDashboardName)
    ?? dashboards[0];
  return [
    { page: '登录页', route: '/login' },
    { page: '问数据-会话状态', route: '/' },
    { page: '问数据-空状态', route: '/?new=1' },
    { page: '问数据-分析结果', route: `/ask/results?q=${encodeURIComponent('统计全部订单收入')}` },
    { page: '数据源列表', route: '/datasources' },
    { page: '数据源详情', route: `/datasources/${primarySource.id}` },
    { page: '数据工作台', route: `/datasources/${primarySource.id}/workspace` },
    { page: '语义模型列表', route: '/semantic-models' },
    { page: '语义模型编辑器', route: `/semantic-models/${primaryModel.id}` },
    { page: '答案库', route: '/answers' },
    { page: '看板列表', route: '/dashboards' },
    { page: '看板详情', route: `/dashboards/${primaryDashboard.id}` },
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

function attributeLocator(attribute: string, value: string): string {
  return `[${attribute}=${JSON.stringify(value)}]`;
}

function actionFor(controlType: string): string {
  if (controlType === 'INPUT') return 'ENTER_VALUE';
  if (controlType === 'DROPDOWN_ACTION') return 'SELECT_OPTION';
  if (controlType === 'UPLOAD') return 'UPLOAD_FILE';
  if (['CHECKBOX', 'RADIO', 'TOGGLE'].includes(controlType)) return 'TOGGLE_STATE';
  return 'CLICK';
}

async function scan(page: Page, target: PageTarget, surface: string): Promise<{
  controls: ControlRecord[];
  hiddenDomInstances: number;
  visibleDomInstances: number;
}> {
  const candidates = await page.locator(selector).evaluateAll((elements) => elements.map((element, index) => {
    const node = element as HTMLElement;
    const input = node as HTMLInputElement;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
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
    const disabled = input.disabled || input.readOnly || node.getAttribute('aria-disabled') === 'true';
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
    return {
      index,
      tag,
      role,
      type,
      text,
      disabled,
      controlType,
      testId: node.dataset.testid ?? null,
      logicalControl: node.dataset.logicalControl ?? null,
      resourceType: node.dataset.resourceType ?? null,
      resourceId: node.dataset.resourceId ?? null,
      href: node instanceof HTMLAnchorElement ? node.getAttribute('href') : null,
      ariaLabel: node.getAttribute('aria-label'),
      optionValues: node instanceof HTMLSelectElement
        ? Array.from(node.options).map((option) => option.value)
        : [],
      styleVisible: !(
        style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0
        || rect.width <= 0 || rect.height <= 0
      ),
    };
  }));
  const playwrightVisibility = await Promise.all(
    candidates.map((item) => page.locator(selector).nth(item.index).isVisible()),
  );
  const visible = candidates.filter((item, index) => item.styleVisible && playwrightVisibility[index]);
  const grouped = new Map<string, ControlRecord>();
  const resourceIds = new Map<string, Set<string>>();
  for (const item of visible) {
    const semanticKey = item.logicalControl
      ? `declared:${item.logicalControl}`
      : [
        'semantic', item.tag, item.role, item.controlType, item.testId ?? '', item.href ?? '',
        item.ariaLabel ?? '', item.text, item.type,
      ].join('|');
    const identity = `${target.route}|${surface}|ADMIN|${semanticKey}`;
    const logicalControlId = `CTL-${createHash('sha256').update(identity).digest('hex').slice(0, 16)}`;
    const locator = item.logicalControl
      ? attributeLocator('data-logical-control', item.logicalControl)
      : item.testId
        ? attributeLocator('data-testid', item.testId)
        : `${selector} >> nth=${item.index}`;
    const domInstance: DomInstance = {
      selector_index: item.index,
      locator: item.resourceId
        ? `${locator}${attributeLocator('data-resource-id', item.resourceId)}`
        : locator,
      control_text: item.text || `[${item.controlType.toLowerCase()}]`,
      enabled: !item.disabled,
      resource_id: item.resourceId,
    };
    const existing = grouped.get(logicalControlId);
    if (existing) {
      existing.dom_instances.push(domInstance);
      existing.dom_instance_count += 1;
      if (item.disabled) existing.disabled_dom_instance_count += 1;
      if (!item.disabled) existing.enabled_state = 'ENABLED';
      if (item.resourceId) resourceIds.get(logicalControlId)!.add(item.resourceId);
      continue;
    }
    resourceIds.set(logicalControlId, new Set(item.resourceId ? [item.resourceId] : []));
    grouped.set(logicalControlId, {
      page: target.page,
      route: target.route,
      control_id: logicalControlId,
      logical_control_id: logicalControlId,
      logical_key: semanticKey,
      control_text: item.text || `[${item.controlType.toLowerCase()}]`,
      control_type: item.controlType,
      tag: item.tag,
      role: item.role,
      test_id: item.testId,
      selector_index: item.index,
      locator,
      href: item.href,
      aria_label: item.ariaLabel,
      input_type: item.type || null,
      option_values: item.optionValues,
      identity_ordinal: 0,
      visible_state: 'VISIBLE',
      enabled_state: item.disabled ? 'DISABLED' : 'ENABLED',
      required_role: 'ADMIN',
      action: actionFor(item.controlType),
      expected_result: 'REQUIRES_CONTROL_SPECIFIC_ACCEPTANCE_MAPPING',
      backend_api: 'NOT_YET_MAPPED',
      database_effect: 'NOT_YET_MAPPED',
      persistence_required: 'NOT_YET_MAPPED',
      current_status: 'INVENTORIED_NOT_FUNCTIONALLY_CERTIFIED',
      surface,
      dom_instance_count: 1,
      disabled_dom_instance_count: item.disabled ? 1 : 0,
      resource_type: item.resourceType,
      resource_instance_count: item.resourceId ? 1 : 0,
      dynamic_resource: Boolean(item.resourceType),
      clone_classification: 'NONE',
      dom_instances: [domInstance],
    });
  }
  const controls = [...grouped.values()];
  for (const control of controls) {
    control.resource_instance_count = resourceIds.get(control.logical_control_id)?.size ?? 0;
    control.clone_classification = control.dom_instance_count === 1
      ? 'NONE'
      : control.dynamic_resource
        ? 'ROW_TEMPLATE_OR_VIRTUALIZED_RESOURCE_INSTANCES'
        : 'RESPONSIVE_OR_PORTAL_CLONE';
  }
  return {
    controls,
    hiddenDomInstances: candidates.length - visible.length,
    visibleDomInstances: visible.length,
  };
}

test('Phase5 real-browser logical control inventory', async ({ page, request }) => {
  test.setTimeout(300_000);
  const inventory: ControlRecord[] = [];
  const pageRows: Array<{
    page: string;
    route: string;
    visible_logical_controls: number;
    actionable_logical_controls: number;
    visible_dom_instances: number;
    hidden_dom_instances: number;
  }> = [];
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
    const result = await scan(page, target, 'BASE_PAGE');
    inventory.push(...result.controls);
    pageRows.push({
      page: target.page,
      route: target.route,
      visible_logical_controls: result.controls.length,
      actionable_logical_controls: result.controls.filter((item) => item.enabled_state === 'ENABLED').length,
      visible_dom_instances: result.visibleDomInstances,
      hidden_dom_instances: result.hiddenDomInstances,
    });
  }
  const identityProjection = inventory.map((item) => ({
    logical_control_id: item.logical_control_id,
    page: item.page,
    route: item.route,
    logical_key: item.logical_key,
    control_type: item.control_type,
    control_text: item.control_text,
    href: item.href,
    aria_label: item.aria_label,
    enabled_state: item.enabled_state,
    required_role: item.required_role,
    action: item.action,
    surface: item.surface,
    resource_type: item.resource_type,
  }));
  const serializedInventory = JSON.stringify(identityProjection);
  const payload = {
    schema_version: CONTROL_INVENTORY_SCHEMA_VERSION,
    control_discovery_rule_hash: CONTROL_DISCOVERY_RULE_HASH,
    control_count_definitions: CONTROL_DISCOVERY_RULES,
    status: 'INVENTORY_COMPLETE_ACCEPTANCE_NOT_CERTIFIED',
    generated_at: new Date().toISOString(),
    browser: 'chromium',
    viewport: { width: 1440, height: 900 },
    role: 'ADMIN',
    page_count: pageRows.length,
    total_visible_controls: inventory.length,
    total_actionable_controls: inventory.filter((item) => item.enabled_state === 'ENABLED').length,
    total_visible_logical_controls: inventory.length,
    total_actionable_logical_controls: inventory.filter((item) => item.enabled_state === 'ENABLED').length,
    total_visible_dom_instances: inventory.reduce((sum, item) => sum + item.dom_instance_count, 0),
    total_hidden_dom_instances: pageRows.reduce((sum, item) => sum + item.hidden_dom_instances, 0),
    total_duplicate_dom_instances: inventory.reduce((sum, item) => sum + Math.max(0, item.dom_instance_count - 1), 0),
    total_tested_controls: 0,
    visible_actionable_control_coverage: 0,
    applicable_control_pass_rate: null,
    noop_control_count: null,
    broken_control_count: null,
    fake_success_count: null,
    paid_provider_calls: 0,
    historical_counts: {
      prior_actionable_early_rule: 391,
      prior_visible_dom_inventory: 901,
      prior_actionable_dom_inventory: 819,
      explanation: '391 and 819 were DOM-instance counts produced by evolving v1 discovery. V2 is a logical-control count: hidden nodes are excluded and responsive, portal, row-template, virtualized-resource, and repeated dynamic-resource instances are deduplicated by LOGICAL_CONTROL_ID while DOM_INSTANCE_COUNT remains observable.',
    },
    acceptance_note: 'Inventory is not functional acceptance; each enabled logical control still requires Browser-API-DB-readback-refresh evidence.',
    pages: pageRows,
    inventory_sha256: createHash('sha256').update(serializedInventory).digest('hex'),
    dom_snapshot_sha256: createHash('sha256').update(JSON.stringify(inventory)).digest('hex'),
    controls: inventory,
  };
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  expect(pageRows).toHaveLength(21);
  expect(inventory.length).toBeGreaterThan(0);
  expect(new Set(inventory.map((item) => item.logical_control_id)).size).toBe(inventory.length);
  expect(CONTROL_DISCOVERY_RULE_HASH).toMatch(/^[0-9a-f]{64}$/);
});
