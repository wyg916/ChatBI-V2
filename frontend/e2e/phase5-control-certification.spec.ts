import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import {
  expect,
  test,
  type APIRequestContext,
  type APIResponse,
  type Locator,
  type Page,
  type TestInfo,
} from '@playwright/test';

import { adminCredentials } from './auth';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';
const inventoryPath = resolve(process.env.CHATBI_PHASE5_CONTROL_INVENTORY ?? 'test-results/phase5-visible-control-inventory.json');
const outputRoot = resolve(process.env.CHATBI_PHASE5_CONTROL_CERTIFICATION ?? 'test-results/phase5-control-certification');
const metadataSchema = process.env.CHATBI_PHASE5_METADATA_SCHEMA ?? '';
const python = process.env.CHATBI_PYTHON ?? 'python';
const runToken = process.env.CHATBI_CONTROL_RUN_TOKEN ?? 'control-run';
const datasourceId = process.env.CHATBI_CONTROL_DATASOURCE_ID ?? '';
const targetSet = process.env.CHATBI_CONTROL_TARGET_SET ?? '';
const requestedControlIds = new Set(
  (process.env.CHATBI_CONTROL_IDS ?? '').split(',').map((item) => item.trim()).filter(Boolean),
);

const selector = [
  'button', 'a[href]', 'input:not([type="hidden"])', 'textarea', 'select',
  '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
  '[role="switch"]', '[role="checkbox"]', '[role="radio"]', '[contenteditable="true"]',
].join(',');

type ControlRecord = {
  page: string;
  route: string;
  control_id: string;
  logical_control_id?: string;
  logical_key?: string;
  control_text: string;
  control_type: 'BUTTON' | 'LINK_ACTION' | 'INPUT' | 'DROPDOWN_ACTION' | 'UPLOAD' | 'TAB' | 'CHECKBOX' | 'TOGGLE' | 'RADIO' | 'ICON_BUTTON' | 'MENU_ITEM';
  tag: string;
  role: string;
  test_id: string | null;
  selector_index: number;
  locator: string;
  href: string | null;
  aria_label: string | null;
  input_type: string | null;
  option_values: string[];
  identity_ordinal?: number;
  visible_state: 'VISIBLE';
  enabled_state: 'ENABLED' | 'DISABLED';
  required_role: 'ADMIN';
  action: string;
  dom_instance_count?: number;
  resource_type?: string | null;
  resource_id?: string | null;
  target_case?: string;
};

type Inventory = {
  schema_version?: string;
  control_discovery_rule_hash?: string;
  inventory_sha256: string;
  total_visible_controls: number;
  total_actionable_controls: number;
  controls: ControlRecord[];
};

type NetworkEvent = { method: string; path: string; status: number | null };
type DbSnapshot = { fingerprint: string; group: string; tables: Record<string, unknown>; secrets_exposed: false };
type ApiReadback = { method: 'GET'; path: string; status: number; body_sha256: string };
type ExplicitNotApplicable = { status: 'NOT_APPLICABLE_WITH_EXPLICIT_REASON'; reason: string };

type ControlReceipt = {
  SCHEMA_VERSION: 'chatbi.v13.phase5.control-receipt.v2';
  CONTROL_ID: string;
  LOGICAL_CONTROL_ID: string;
  DOM_INSTANCE_COUNT: number;
  PAGE: string;
  ROUTE: string;
  ROLE: 'ADMIN';
  TYPE: string;
  LOCATOR: string;
  VISIBLE: boolean;
  ENABLED: boolean;
  ACTION: string;
  EXPECTED_RESULT: string;
  NETWORK_REQUEST: string[] | ExplicitNotApplicable;
  HTTP_STATUS: number[];
  DB_EFFECT_TYPE: string;
  DB_BEFORE: DbSnapshot | ExplicitNotApplicable | null;
  DB_AFTER: DbSnapshot | ExplicitNotApplicable | null;
  API_READBACK: ApiReadback[] | ExplicitNotApplicable;
  NETWORK_API: { status: 'APPLICABLE' | 'NOT_APPLICABLE_WITH_EXPLICIT_REASON'; reason: string };
  REFRESH_RESULT: Record<string, unknown>;
  FINAL_STATUS: 'PASS' | 'FAIL';
  FAIL_REASON: string | null;
  EVIDENCE: Record<string, unknown>;
  PAID_PROVIDER_CALLS: 0;
  PAID_PROVIDER_COST_CNY: 0;
};

type ActionResult = {
  expectedResult: string;
  observable: string;
  cleanup?: () => Promise<void>;
};

type DynamicResourceType = 'TRACE' | 'CONVERSATION' | 'QUERY_RUN' | 'EVAL_RUN' | 'ARTIFACT' | 'SHARE';
type DynamicTraceFixture = {
  resource_id: string;
  resource_type: 'TRACE';
  created_at: string;
  owning_workspace: string;
  owning_user: string;
  conversation_id: string;
  db_before: DbSnapshot;
  db_after_create: DbSnapshot;
  create_api_statuses: number[];
  provider: string;
  cleanup_status?: 'PASS';
};

function sha256(value: string | Buffer): string {
  return createHash('sha256').update(value).digest('hex');
}

function atomicJson(path: string, payload: unknown) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  renameSync(temporary, path);
}

function safePath(raw: string): string {
  const url = new URL(raw, apiBase);
  for (const key of ['token', 'password', 'secret', 'key']) {
    if (url.searchParams.has(key)) url.searchParams.set(key, '<REDACTED>');
  }
  return `${url.pathname}${url.search}`;
}

async function responseJson(response: APIResponse): Promise<any> {
  const body = await response.text();
  expect(response.ok(), `${response.status()} ${safePath(response.url())}`).toBeTruthy();
  return body ? JSON.parse(body) : null;
}

async function list(request: APIRequestContext, path: string): Promise<any[]> {
  const body = await responseJson(await request.get(`${apiBase}${path}`));
  return Array.isArray(body) ? body : body.items;
}

function mutationGroup(control: ControlRecord): string | null {
  const text = control.control_text;
  if (control.resource_type === 'TRACE') return 'trace';
  if (control.page === '登录页' && text === '登录 ChatBI Studio') return 'auth';
  if (text === '退出登录') return 'auth';
  if (control.page.startsWith('问数据')) {
    if (text === '添加文件或图片') return 'chat';
    if (control.control_type === 'DROPDOWN_ACTION' && text.startsWith('移动会话 ')) return 'chat';
    if (control.control_type === 'INPUT' && text === '新项目名称') return 'chat';
    if ([
      '置顶', '取消置顶', '归档', '恢复', '共享', '删除', '重命名', '重新生成',
      '结果有帮助', '需要改进', '按地区拆分看看？', '按月查看趋势怎么样？',
      '对比收入与利润表现？', '哪个客户贡献最高？',
    ].includes(text)) return 'chat';
    if (/^(销|品|客|区)/.test(text)) return 'chat';
  }
  if (control.page === '数据源详情' && ['刷新数据', '编辑设置'].includes(text)) return 'datasource';
  if (control.page.startsWith('语义模型')) {
    if (
      ['＋ 新建语义模型', '导入模型', '选择语义模型文件', '保存模型', '添加实体'].includes(text)
      || text.startsWith('发布 ')
    ) return 'semantic';
  }
  if (control.page === '答案库' && ['＋ 新建标准答案', '批量导入'].includes(text)) return 'answers';
  if (control.page === '看板列表' && ['＋ 新建看板', '导入模板'].includes(text)) return 'dashboards';
  if (control.page.startsWith('评测') && ['▶ 快速运行 Golden 50', '新建评测', '重新运行'].includes(text)) return 'evaluation';
  return null;
}

function dbSnapshot(group: string, workspaceId: string): DbSnapshot {
  if (!metadataSchema) throw new Error('CHATBI_PHASE5_METADATA_SCHEMA is required');
  const script = resolve('..', 'scripts', 'phase5-control-db-probe.py');
  const result = spawnSync(python, [
    script, 'snapshot', '--schema', metadataSchema, '--group', group,
    '--workspace-id', workspaceId,
  ], {
    cwd: resolve('..'),
    env: process.env,
    encoding: 'utf8',
    windowsHide: true,
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.status !== 0) throw new Error(`DB_PROBE_FAILED:${result.stderr || result.stdout}`);
  return JSON.parse(result.stdout) as DbSnapshot;
}

class DynamicResourceFixtureManager {
  static readonly supportedResourceTypes: readonly DynamicResourceType[] = [
    'TRACE', 'CONVERSATION', 'QUERY_RUN', 'EVAL_RUN', 'ARTIFACT', 'SHARE',
  ];

  constructor(
    private readonly request: APIRequestContext,
    private readonly workspaceId: string,
    private readonly userId: string,
  ) {}

  async create(resourceType: DynamicResourceType, caseId: string): Promise<DynamicTraceFixture> {
    if (resourceType !== 'TRACE') {
      throw new Error(`Dynamic fixture generation is not implemented for ${resourceType}`);
    }
    const dbBefore = dbSnapshot('trace', this.workspaceId);
    const conversationResponse = await this.request.post(`${apiBase}/conversations`, {
      data: { title: `Phase5 TRACE ${runToken} ${caseId}` },
    });
    expect(conversationResponse.status(), `${caseId} create conversation`).toBe(201);
    const conversation = await conversationResponse.json();
    const messageId = `p5-${runToken}-${caseId}-${Date.now()}`.slice(0, 120);
    const chatResponse = await this.request.post(`${apiBase}/chat`, {
      data: {
        conversation_id: conversation.id,
        client_message_id: messageId,
        content: '今天是几号？',
        attachment_ids: [],
      },
      timeout: 30_000,
    });
    expect(chatResponse.status(), `${caseId} create deterministic trace`).toBe(201);
    const chat = await chatResponse.json();
    const tracePayload = chat.assistant_message?.trace_payload ?? {};
    const traceId = String(tracePayload.trace_id ?? '');
    expect(traceId, `${caseId} trace identity`).toMatch(/^TRACE-/);
    expect(tracePayload.model_provider, `${caseId} provider must be deterministic`).toBe('none');
    expect(tracePayload.model_name, `${caseId} model must be deterministic`).toBe('none');
    const indexResponse = await this.request.get(`${apiBase}/governance/traces?limit=200`);
    expect(indexResponse.status(), `${caseId} bounded trace index readback`).toBe(200);
    const index = await indexResponse.json();
    const currentTrace = index.items.find((item: any) => item.trace_id === traceId);
    expect(currentTrace, `${caseId} current trace in bounded index`).toBeTruthy();
    expect(String(currentTrace.workspace_id)).toBe(this.workspaceId);
    expect(String(currentTrace.user_id)).toBe(this.userId);
    const dbAfterCreate = dbSnapshot('trace', this.workspaceId);
    expect(dbAfterCreate.fingerprint, `${caseId} trace persisted in database`).not.toBe(dbBefore.fingerprint);
    return {
      resource_id: traceId,
      resource_type: 'TRACE',
      created_at: String(currentTrace.started_at),
      owning_workspace: String(currentTrace.workspace_id),
      owning_user: String(currentTrace.user_id),
      conversation_id: String(conversation.id),
      db_before: dbBefore,
      db_after_create: dbAfterCreate,
      create_api_statuses: [conversationResponse.status(), chatResponse.status(), indexResponse.status()],
      provider: 'none',
    };
  }

  bind(control: ControlRecord, fixture: DynamicTraceFixture): ControlRecord {
    return {
      ...control,
      control_text: '查看 TRACE 详情',
      locator: `[data-logical-control="governance.trace.open-detail"][data-resource-id=${JSON.stringify(fixture.resource_id)}]`,
      resource_type: fixture.resource_type,
      resource_id: fixture.resource_id,
      aria_label: '查看 TRACE 详情',
      identity_ordinal: 0,
    };
  }

  async cleanup(fixture: DynamicTraceFixture): Promise<Record<string, unknown>> {
    const response = await this.request.delete(`${apiBase}/conversations/${fixture.conversation_id}`);
    expect([204, 404], `${fixture.resource_id} exact conversation cleanup`).toContain(response.status());
    const conversation = await this.request.get(`${apiBase}/conversations/${fixture.conversation_id}`);
    expect(conversation.status(), `${fixture.resource_id} owning conversation removed after cleanup`).toBe(404);
    const dbAfterCleanup = dbSnapshot('trace', this.workspaceId);
    expect(dbAfterCleanup.fingerprint, `${fixture.resource_id} database cleanup`).toBe(fixture.db_before.fingerprint);
    fixture.cleanup_status = 'PASS';
    return {
      status: 'PASS',
      delete_http_status: response.status(),
      conversation_readback_http_status: conversation.status(),
      db_restored_to_baseline: true,
    };
  }
}

async function apiReadback(request: APIRequestContext, control: ControlRecord): Promise<ApiReadback[]> {
  const paths: string[] = [];
  if (control.resource_type === 'TRACE' && control.resource_id) {
    paths.push('/governance/traces?limit=200');
  } else if (control.page === '登录页' || control.control_text === '退出登录') paths.push('/auth/me');
  else if (control.page.startsWith('问数据')) paths.push('/conversations?state=all', '/projects?state=all');
  else if (control.page.startsWith('数据源')) {
    const id = control.route.match(/^\/datasources\/([^/?]+)/)?.[1];
    paths.push(id ? `/datasources/${id}` : '/datasources');
    if (id) paths.push(`/datasources/${id}/schemas`);
  } else if (control.page.startsWith('语义模型')) {
    const id = control.route.match(/^\/semantic-models\/([^/?]+)/)?.[1];
    paths.push(id ? `/semantic-models/${id}` : '/semantic-models');
  } else if (control.page === '答案库') paths.push('/answers?page_size=100');
  else if (control.page.startsWith('看板')) {
    const id = control.route.match(/^\/dashboards\/([^/?]+)/)?.[1];
    paths.push(id ? `/dashboards/${id}` : '/dashboards?page_size=100');
  } else if (control.page.startsWith('评测')) paths.push('/evaluation/overview');
  const receipts: ApiReadback[] = [];
  for (const path of paths) {
    const response = await request.get(`${apiBase}${path}`);
    const body = await response.text();
    if (control.resource_type === 'TRACE' && control.resource_id) {
      const payload = JSON.parse(body);
      expect(payload.items.some((item: any) => item.trace_id === control.resource_id), `${control.control_id} current trace index readback`).toBe(true);
    }
    receipts.push({ method: 'GET', path, status: response.status(), body_sha256: sha256(body) });
  }
  return receipts;
}

async function domReceipt(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(async () => {
    const main = document.querySelector('main') ?? document.body;
    const html = main.outerHTML;
    const text = (main.textContent ?? '').replace(/\s+/g, ' ').trim();
    const digest = async (value: string) => Array.from(new Uint8Array(
      await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)),
    )).map((item) => item.toString(16).padStart(2, '0')).join('');
    return {
      url: location.href,
      html_sha256: await digest(html),
      text_sha256: await digest(text),
      dialog_count: document.querySelectorAll('[role="dialog"], [role="alertdialog"]').length,
      fullscreen: Boolean(document.fullscreenElement),
    };
  });
}

async function ensureAuthenticated(page: Page) {
  let response = await page.context().request.get(`${apiBase}/auth/me`);
  if (response.status() === 200) return;
  response = await page.context().request.post(`${apiBase}/auth/login`, {
    data: { email: adminCredentials.email, password: adminCredentials.password, remember: false },
  });
  expect(response.status(), 'restore control-runner session').toBe(200);
}

async function resetChatFixtures(request: APIRequestContext) {
  for (const conversation of await list(request, '/conversations?state=all')) {
    const response = await request.delete(`${apiBase}/conversations/${conversation.id}`);
    expect([204, 404]).toContain(response.status());
  }
  for (const project of await list(request, '/projects?state=active')) {
    const response = await request.post(`${apiBase}/projects/${project.id}/archive`);
    expect(response.ok()).toBeTruthy();
  }
}

async function preparePage(page: Page, request: APIRequestContext, control: ControlRecord) {
  if (control.route !== '/login') await ensureAuthenticated(page);
  if (control.page.startsWith('问数据')) {
    await resetChatFixtures(request);
    if (control.control_type === 'DROPDOWN_ACTION' && control.control_text.startsWith('移动会话 ')) {
      const response = await request.post(`${apiBase}/projects`, {
        data: { name: `Phase5 Control Project ${runToken}` },
      });
      expect(response.status(), 'create run-scoped move target').toBe(201);
    }
  }
  const response = await page.goto(control.route, { waitUntil: 'domcontentloaded' });
  expect(response?.status(), `${control.page} direct route`).toBe(200);
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => undefined);
  if (control.page === '问数据-分析结果') {
    await expect(page.locator('[data-testid^="result-state-"]').last()).toBeVisible({ timeout: 60_000 });
  }
}

async function locateControl(page: Page, control: ControlRecord): Promise<Locator> {
  if (control.resource_type && control.resource_id) {
    const resourceLocator = page.locator(control.locator);
    await expect(resourceLocator, `${control.control_id} current dynamic resource`).toHaveCount(1);
    await expect(resourceLocator, `${control.control_id} locator`).toBeVisible({ timeout: 10_000 });
    await expect(resourceLocator, `${control.control_id} enabled`).toBeEnabled();
    await resourceLocator.scrollIntoViewIfNeeded();
    return resourceLocator;
  }
  const matchingIndexes = async () => {
    const candidates = await page.locator(selector).evaluateAll((elements, expected) => elements.flatMap((element, index) => {
      const node = element as HTMLElement;
      const input = node as HTMLInputElement;
      const text = (
        node.getAttribute('aria-label')
        || node.getAttribute('title')
        || node.textContent
        || input.placeholder
        || input.value
        || ''
      ).replace(/\s+/g, ' ').trim().slice(0, 240);
      if (
        node.tagName.toLowerCase() !== expected.tag
        || (node.getAttribute('role') ?? '') !== expected.role
        || (expected.testId === null && text !== expected.text)
        || (expected.testId !== null && node.dataset.testid !== expected.testId)
        || (expected.href !== null && node.getAttribute('href') !== expected.href)
        || (expected.ariaLabel !== null && node.getAttribute('aria-label') !== expected.ariaLabel)
      ) return [];
      return [index];
    }), {
      tag: control.tag,
      role: control.role,
      text: control.control_text,
      testId: control.test_id,
      href: control.href,
      ariaLabel: control.aria_label,
    });
    const visibility = await Promise.all(candidates.map((index) => page.locator(selector).nth(index).isVisible()));
    return candidates.filter((_index, index) => visibility[index]);
  };
  const fallbackIdentity = /^\[[a-z_-]+-\d+\]$/i.test(control.control_text);
  let indexes = fallbackIdentity ? [control.selector_index] : await matchingIndexes();
  const ordinal = control.identity_ordinal ?? 0;
  if (indexes.length <= ordinal && control.page.startsWith('问数据')) {
    const activeMenu = page.locator('.conversation-item.active .conversation-menu summary');
    if (await activeMenu.count()) await activeMenu.click();
    indexes = fallbackIdentity ? [control.selector_index] : await matchingIndexes();
  }
  expect(indexes.length, `${control.control_id} identity candidates`).toBeGreaterThan(ordinal);
  const locator = page.locator(selector).nth(indexes[ordinal]);
  await expect(locator, `${control.control_id} locator`).toBeVisible({ timeout: 10_000 });
  await expect(locator, `${control.control_id} enabled`).toBeEnabled();
  expect(await locator.evaluate((node) => node.tagName.toLowerCase())).toBe(control.tag);
  await locator.scrollIntoViewIfNeeded();
  return locator;
}

function fixtureFile(kind: 'answer' | 'dashboard' | 'semantic', control: ControlRecord): string {
  const directory = resolve(outputRoot, 'fixtures');
  mkdirSync(directory, { recursive: true });
  const suffix = control.control_id.slice(-8);
  const path = resolve(directory, `${kind}-${suffix}.json`);
  const payload = kind === 'answer'
    ? [{
      question: `Phase5 Control Answer ${runToken} ${suffix}`,
      model_name: 'Phase5 Control Certification',
      owner_name: 'Phase5 Control Certification',
      module: 'Phase5 Control Certification',
      status: 'DRAFT',
      accuracy_percent: 0,
    }]
    : kind === 'dashboard'
      ? [{
        name: `Phase5 Control Dashboard ${runToken} ${suffix}`,
        description: 'Run-scoped imported dashboard control fixture',
        is_shared: false,
      }]
      : {
        name: `Phase5 Control Semantic ${runToken} ${suffix}`,
        description: 'Run-scoped imported semantic control fixture',
        datasource_id: datasourceId,
      };
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return path;
}

function attachmentFixture(control: ControlRecord): string {
  const directory = resolve(outputRoot, 'fixtures');
  mkdirSync(directory, { recursive: true });
  const path = resolve(directory, `attachment-${control.control_id.slice(-8)}.csv`);
  writeFileSync(path, 'region,revenue\nEast,270\n', 'utf8');
  return path;
}

async function createAnswer(page: Page, control: ControlRecord): Promise<ActionResult> {
  await page.getByRole('button', { name: '＋ 新建标准答案' }).click();
  const dialog = page.getByRole('dialog', { name: '新建标准答案' });
  await dialog.getByLabel('标准问题').fill(`Phase5 Control Answer ${runToken} ${control.control_id.slice(-8)}`);
  await dialog.getByLabel('语义模型').fill('Phase5 Control Certification');
  await dialog.getByLabel('责任人').fill('Phase5 Control Certification');
  const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/answers') && item.request().method() === 'POST');
  await dialog.getByRole('button', { name: '保存标准答案' }).click();
  expect((await response).status()).toBe(201);
  await expect(dialog).toHaveCount(0);
  return { expectedResult: 'ANSWER_CREATED_API_DB_UI', observable: 'answer create dialog submitted' };
}

async function importContent(page: Page, control: ControlRecord, kind: 'answer' | 'dashboard'): Promise<ActionResult> {
  const title = kind === 'answer' ? '批量导入标准答案' : '导入看板模板';
  await page.getByRole('button', { name: control.control_text }).click();
  const dialog = page.getByRole('dialog', { name: title });
  await dialog.locator('input[type="file"]').setInputFiles(fixtureFile(kind, control));
  const suffix = kind === 'answer' ? '/api/v1/answers' : '/api/v1/dashboards';
  const response = page.waitForResponse((item) => item.url().endsWith(suffix) && item.request().method() === 'POST');
  await dialog.getByRole('button', { name: '校验并导入' }).click();
  expect((await response).status()).toBe(201);
  await expect(dialog).toHaveCount(0);
  return { expectedResult: `${kind.toUpperCase()}_IMPORT_API_DB_UI`, observable: `${kind} JSON imported` };
}

async function createDashboard(page: Page, control: ControlRecord): Promise<ActionResult> {
  await page.getByRole('button', { name: '＋ 新建看板' }).click();
  const dialog = page.getByRole('dialog', { name: '新建看板' });
  await dialog.getByLabel('看板名称').fill(`Phase5 Control Dashboard ${runToken} ${control.control_id.slice(-8)}`);
  await dialog.getByLabel('看板说明').fill('Run-scoped dashboard created by the Phase5 control runner');
  const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/dashboards') && item.request().method() === 'POST');
  await dialog.getByRole('button', { name: '创建看板' }).click();
  expect((await response).status()).toBe(201);
  await expect(dialog).toHaveCount(0);
  return { expectedResult: 'DASHBOARD_CREATED_API_DB_UI', observable: 'dashboard create dialog submitted' };
}

async function importSemantic(page: Page, control: ControlRecord, locator?: Locator): Promise<ActionResult> {
  if (!datasourceId) throw new Error('CHATBI_CONTROL_DATASOURCE_ID is required');
  const path = fixtureFile('semantic', control);
  const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/semantic-models') && item.request().method() === 'POST');
  if (control.control_type === 'UPLOAD') await (locator ?? page.locator('input[type="file"]')).setInputFiles(path);
  else {
    const chooser = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: '导入模型' }).click();
    await (await chooser).setFiles(path);
  }
  expect((await response).status()).toBe(201);
  await page.waitForURL(/\/semantic-models\//);
  return { expectedResult: 'SEMANTIC_IMPORT_API_DB_UI', observable: 'semantic model imported and opened' };
}

async function createSemantic(page: Page, control: ControlRecord): Promise<ActionResult> {
  if (!datasourceId) throw new Error('CHATBI_CONTROL_DATASOURCE_ID is required');
  await page.getByRole('button', { name: '＋ 新建语义模型' }).click();
  const dialog = page.getByRole('dialog', { name: '新建语义模型' });
  await dialog.getByLabel('模型名称').fill(`Phase5 Control Semantic ${runToken} ${control.control_id.slice(-8)}`);
  await dialog.getByLabel('数据源').selectOption(datasourceId);
  const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/semantic-models') && item.request().method() === 'POST');
  await dialog.getByRole('button', { name: '创建并打开编辑器' }).click();
  expect((await response).status()).toBe(201);
  await page.waitForURL(/\/semantic-models\//);
  return { expectedResult: 'SEMANTIC_CREATED_API_DB_UI', observable: 'semantic model created and opened' };
}

async function performAction(page: Page, control: ControlRecord, locator: Locator, testInfo: TestInfo): Promise<ActionResult> {
  const text = control.control_text;
  if (control.resource_type === 'TRACE' && control.resource_id) {
    const response = page.waitForResponse((item) => (
      item.request().method() === 'GET'
      && new URL(item.url()).pathname.endsWith(`/api/v1/governance/traces/${control.resource_id}`)
    ));
    await locator.click();
    expect((await response).status(), `${control.control_id} current trace detail`).toBe(200);
    await expect(page.getByRole('heading', { name: 'Trace 阶段详情' })).toBeVisible();
    return {
      expectedResult: 'CURRENT_TRACE_API_DB_UI',
      observable: `current trace selected sha256=${sha256(control.resource_id)}`,
    };
  }
  if (control.page === '登录页' && text === '登录 ChatBI Studio') {
    await page.getByLabel('账号或电子名').fill(adminCredentials.email);
    await page.getByLabel('密码').fill(adminCredentials.password);
    const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/auth/login') && item.request().method() === 'POST');
    await locator.click();
    expect((await response).status()).toBe(200);
    await expect(page).toHaveURL('/');
    return { expectedResult: 'AUTH_SESSION_CREATED_AND_DEFAULT_ROUTE_OPENED', observable: 'authenticated homepage visible' };
  }
  if (text === '退出登录') {
    const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/auth/logout') && item.request().method() === 'POST');
    await locator.click();
    expect((await response).status()).toBe(204);
    await expect(page).toHaveURL('/login');
    return { expectedResult: 'AUTH_SESSION_REVOKED_AND_LOGIN_ROUTE_OPENED', observable: 'logout completed' };
  }
  if (control.control_type === 'LINK_ACTION') {
    const href = await locator.getAttribute('href');
    expect(href, 'link href').toBeTruthy();
    const expected = new URL(href!, page.url());
    await Promise.all([
      page.waitForURL((url) => url.pathname === expected.pathname && url.search === expected.search),
      locator.click(),
    ]);
    expect(new URL(page.url()).pathname).toBe(expected.pathname);
    return { expectedResult: 'ROUTE_NAVIGATION_MATCHES_HREF', observable: `navigated to ${expected.pathname}` };
  }
  if (control.control_type === 'INPUT') {
    const value = text === '请输入账号或电子名' ? adminCredentials.email
      : text === '请输入密码' ? adminCredentials.password
        : control.input_type === 'number' ? '1'
          : control.input_type === 'date' ? '2026-08-01'
            : control.input_type === 'datetime-local' ? '2026-08-01T08:00'
              : control.input_type === 'month' ? '2026-08'
                : control.input_type === 'time' ? '08:00'
            : `phase5-${runToken}-${control.control_id.slice(-6)}`;
    await locator.fill(value);
    if (text === '新项目名称') {
      const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/projects') && item.request().method() === 'POST');
      await locator.press('Enter');
      expect((await response).status()).toBe(201);
      return { expectedResult: 'PROJECT_CREATED_API_DB_UI', observable: 'project created from input' };
    }
    expect(await locator.inputValue()).toBe(value);
    await page.waitForTimeout(300);
    return { expectedResult: 'INPUT_VALUE_ACCEPTED_AND_UI_REACTED', observable: 'input value round-tripped' };
  }
  if (control.control_type === 'DROPDOWN_ACTION') {
    const current = await locator.inputValue();
    const options = await locator.locator('option').evaluateAll((items) => items.map((item) => ({
      value: (item as HTMLOptionElement).value,
      disabled: (item as HTMLOptionElement).disabled,
    })));
    const alternate = options.find((item) => !item.disabled && item.value !== current);
    if (!alternate) {
      expect(options.some((item) => !item.disabled && item.value === current), 'selected singleton option').toBe(true);
      await locator.selectOption(current);
      expect(await locator.inputValue()).toBe(current);
      return {
        expectedResult: 'SINGLE_AVAILABLE_OPTION_CONFIRMED',
        observable: `selected singleton option sha256=${sha256(current)}`,
      };
    }
    await locator.selectOption(alternate.value);
    expect(await locator.inputValue()).toBe(alternate.value);
    await page.waitForTimeout(500);
    return {
      expectedResult: text.startsWith('移动会话 ') ? 'CONVERSATION_PROJECT_PERSISTED' : 'FILTER_OR_SELECTION_APPLIED',
      observable: `selected option sha256=${sha256(alternate.value)}`,
    };
  }
  if (control.control_type === 'UPLOAD') return importSemantic(page, control, locator);
  if (control.page.startsWith('问数据') && text === '＋ 新会话') {
    await locator.click();
    await expect(page.getByLabel('输入业务问题')).toBeVisible();
    await expect(page.getByLabel('输入业务问题')).toHaveValue('');
    return { expectedResult: 'NEW_CONVERSATION_COMPOSER_READY', observable: 'empty authenticated composer ready' };
  }
  if (control.page.startsWith('问数据') && text === '添加文件或图片') {
    const response = page.waitForResponse((item) => item.url().endsWith('/api/v1/attachments') && item.request().method() === 'POST');
    const chooser = page.waitForEvent('filechooser');
    await locator.click();
    const path = attachmentFixture(control);
    await (await chooser).setFiles(path);
    expect((await response).status()).toBe(201);
    await expect(page.getByText(path.split(/[\\/]/).at(-1)!, { exact: true })).toBeVisible();
    return { expectedResult: 'ATTACHMENT_UPLOAD_API_DB_UI', observable: 'sanitized CSV attachment reached READY UI state' };
  }
  if (control.page === '问数据-分析结果' && text === '查看 SQL 与执行明细') {
    await page.getByRole('button', { name: '查看 SQL 与执行明细', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'SQL 与执行明细' })).toBeVisible();
    return { expectedResult: 'EVIDENCE_DRAWER_VISIBLE', observable: 'SQL and execution evidence drawer opened' };
  }
  if (control.page === '看板详情' && text === '全屏') {
    await locator.click();
    await page.waitForFunction(() => Boolean(document.fullscreenElement));
    return { expectedResult: 'DOCUMENT_FULLSCREEN_ACTIVE', observable: 'documentElement entered fullscreen' };
  }
  if (control.page === '看板详情' && text === '↻ 刷新') {
    const response = page.waitForResponse((item) => item.request().method() === 'GET' && item.url().includes('/api/v1/dashboards/'));
    await locator.click();
    expect((await response).status()).toBe(200);
    return { expectedResult: 'DASHBOARD_REFRESH_API_UI', observable: 'dashboard query cache refetched from API' };
  }
  if (control.page === '答案库' && text === '＋ 新建标准答案') return createAnswer(page, control);
  if (control.page === '答案库' && text === '批量导入') return importContent(page, control, 'answer');
  if (control.page === '看板列表' && text === '＋ 新建看板') return createDashboard(page, control);
  if (control.page === '看板列表' && text === '导入模板') return importContent(page, control, 'dashboard');
  if (control.page === '语义模型列表' && text === '＋ 新建语义模型') return createSemantic(page, control);
  if (control.page === '语义模型列表' && text === '导入模型') return importSemantic(page, control);
  if (control.page === '数据源详情' && text === '编辑设置') {
    await locator.click();
    const dialog = page.getByRole('dialog', { name: '编辑数据源设置' });
    const name = dialog.getByLabel('数据源名称');
    await name.fill(`${await name.inputValue()} Control`);
    const response = page.waitForResponse((item) => item.url().includes('/api/v1/datasources/') && item.request().method() === 'PUT');
    await dialog.getByRole('button', { name: '保存设置' }).click();
    expect((await response).status()).toBe(200);
    await expect(dialog).toHaveCount(0);
    return { expectedResult: 'DATASOURCE_SETTINGS_API_DB_READBACK', observable: 'same-value safe update persisted' };
  }
  if (control.page === '语义模型编辑器' && text === '添加实体') {
    await locator.click();
    const dialog = page.getByRole('dialog', { name: '添加实体' });
    const suffix = control.control_id.slice(-6);
    await dialog.getByLabel('实体名称').fill(`phase5_entity_${suffix}`);
    await dialog.getByLabel('物理表名').fill('orders');
    await dialog.getByLabel('主键').fill('order_id');
    const response = page.waitForResponse((item) => item.url().includes('/entities') && item.request().method() === 'POST');
    await dialog.getByRole('button', { name: '保存实体' }).click();
    expect((await response).status()).toBe(201);
    await expect(dialog).toHaveCount(0);
    return { expectedResult: 'SEMANTIC_ENTITY_API_DB_UI', observable: 'entity created in run-scoped model' };
  }
  if (control.page === '语义模型编辑器' && text === '保存模型') {
    const name = page.locator('.semantic-config-panel input').first();
    await name.fill(`${await name.inputValue()}_ctl`);
  }
  if (control.page === '语义模型编辑器' && text.startsWith('发布 ')) {
    const name = page.locator('.semantic-config-panel input').first();
    const current = await name.inputValue();
    if (current.endsWith('_ctl')) {
      await name.fill(current.slice(0, -4));
      const saveResponse = page.waitForResponse((item) => item.request().method() === 'PUT' && item.url().includes('/api/v1/semantic-models/'));
      await page.getByTestId('save-model').click();
      expect((await saveResponse).status()).toBe(200);
      await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => undefined);
    }
    const publishResponse = page.waitForResponse((item) => item.request().method() === 'POST' && item.url().endsWith('/publish'));
    await page.getByTestId('publish-model').click();
    expect((await publishResponse).status()).toBe(200);
    await expect(page.getByRole('status')).toContainText('语义模型已发布');
    return { expectedResult: 'SEMANTIC_PUBLISH_API_DB_UI', observable: 'valid run-scoped model published with version receipt' };
  }
  if (control.page === '治理中心-成本与用量' && text === '应用筛选') {
    const dates = page.locator('.governance-filters input[type="datetime-local"]');
    await dates.nth(0).fill('2026-08-01T00:00');
    await dates.nth(1).fill('2026-08-23T23:59');
    const response = page.waitForResponse((item) => item.request().method() === 'GET' && item.url().includes('/api/v1/governance/cost'));
    await locator.click();
    expect((await response).status()).toBe(200);
    return { expectedResult: 'COST_FILTER_API_QUERY_UI', observable: 'time-bounded cost query completed' };
  }
  if (control.page === '治理中心-成本与用量' && text === '重置') {
    const dates = page.locator('.governance-filters input[type="datetime-local"]');
    await dates.nth(0).fill('2026-08-01T00:00');
    await dates.nth(1).fill('2026-08-23T23:59');
    await locator.click();
    await expect(dates.nth(0)).toHaveValue('');
    await expect(dates.nth(1)).toHaveValue('');
    return { expectedResult: 'FILTER_RESET_CONFIRMED', observable: 'draft and applied filters reset to empty state' };
  }
  if (control.page.startsWith('问数据') && text === '重命名') {
    await locator.click();
    const rename = page.locator('.conversation-item.active input[aria-label^="重命名会话"]');
    await rename.fill(`Phase5 Control Conversation ${control.control_id.slice(-6)}`);
    const response = page.waitForResponse((item) => item.request().method() === 'PATCH' && item.url().includes('/api/v1/conversations/'));
    await page.locator('.conversation-item.active').getByRole('button', { name: '保存' }).click();
    expect((await response).status()).toBe(200);
    return { expectedResult: 'CONVERSATION_RENAME_API_DB_UI', observable: 'renamed conversation visible' };
  }
  if (control.page.startsWith('问数据') && text === '删除') {
    await locator.click();
    const confirm = page.getByRole('alertdialog').getByRole('button', { name: '确认删除' });
    const response = page.waitForResponse((item) => item.request().method() === 'DELETE' && item.url().includes('/api/v1/conversations/'));
    await confirm.click();
    expect((await response).status()).toBe(204);
    return { expectedResult: 'CONVERSATION_DELETE_API_DB_REFRESH', observable: 'conversation removed' };
  }
  if (control.page.startsWith('问数据') && text === '共享') {
    await locator.click();
    const dialog = page.getByRole('dialog', { name: /共享会话/ });
    const response = page.waitForResponse((item) => item.request().method() === 'POST' && /\/api\/v1\/conversations\/[^/]+\/shares$/.test(new URL(item.url()).pathname));
    await dialog.getByRole('button', { name: '创建受控链接' }).click();
    expect((await response).status()).toBe(201);
    await expect(dialog.getByLabel('共享链接')).toBeVisible();
    return { expectedResult: 'CONTROLLED_SHARE_API_DB_UI', observable: 'share link created without recording value' };
  }
  if (/^复制 (SQL|回答)$/.test(text)) {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await locator.click();
    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard.trim().length).toBeGreaterThan(0);
    return { expectedResult: 'CLIPBOARD_NON_EMPTY', observable: `clipboard_sha256=${sha256(clipboard)}` };
  }
  if (text === '导出') {
    const download = page.waitForEvent('download');
    await locator.click();
    const item = await download;
    const path = await item.path();
    expect(path).toBeTruthy();
    const bytes = readFileSync(path!);
    expect(bytes.length).toBeGreaterThan(0);
    return { expectedResult: 'NON_EMPTY_DOWNLOAD_WITH_HASH', observable: `download_sha256=${sha256(bytes)}` };
  }
  const initiallyActive = await locator.evaluate((node) => (
    node.getAttribute('aria-selected') === 'true'
    || node.getAttribute('aria-current') !== null
    || node.classList.contains('active')
  ));
  const completesChatTurn = text === '重新生成' || /^(销|品|客|区)/.test(text) || /看看？$|怎么样？$|表现？$|最高？$/.test(text);
  const assistantCountBefore = completesChatTurn ? await page.locator('.chat-assistant-message').count() : 0;
  await locator.click();
  if (completesChatTurn) {
    await page.waitForFunction((before) => {
      const messages = Array.from(document.querySelectorAll('.chat-assistant-message'));
      const latest = messages.at(-1);
      return messages.length > before && Boolean(latest) && !latest!.querySelector('.assistant-response.pending');
    }, assistantCountBefore, { timeout: 60_000 });
    await expect(page.locator('[data-testid^="result-state-"]').last()).toBeVisible({ timeout: 60_000 });
  } else {
    await page.waitForTimeout(800);
  }
  if (mutationGroup(control)) {
    await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => undefined);
  }
  if (initiallyActive) {
    const stillActive = await locator.evaluate((node) => (
      node.getAttribute('aria-selected') === 'true'
      || node.getAttribute('aria-current') !== null
      || node.classList.contains('active')
    )).catch(() => true);
    expect(stillActive).toBe(true);
    return { expectedResult: 'ACTIVE_CONTROL_IDEMPOTENT', observable: 'active state remained selected' };
  }
  return { expectedResult: 'OBSERVABLE_UI_NETWORK_OR_STATE_TRANSITION', observable: `clicked via ${testInfo.project.name || 'chromium'}` };
}

function executionRank(control: ControlRecord): number {
  if (control.page === '治理中心-ONE_TRACE') return 0;
  const group = mutationGroup(control);
  if (!group) return 10;
  if (control.control_text === '删除') return 90;
  if (control.control_text === '归档') return 80;
  if (control.control_text.startsWith('发布 ')) return 75;
  if (['＋ 新建标准答案', '批量导入', '＋ 新建看板', '导入模板', '＋ 新建语义模型', '导入模型', '选择语义模型文件', '添加实体'].includes(control.control_text)) return 70;
  return 60;
}

function previousOneTraceForty(inventory: Inventory): ControlRecord[] {
  const controls = inventory.controls.filter((item) => (
    item.page === '治理中心-ONE_TRACE' && item.enabled_state === 'ENABLED'
  ));
  const descriptors: Array<{ kind: 'href' | 'text'; value: string }> = [
    { kind: 'href', value: '/' },
    { kind: 'href', value: '/datasources' },
    { kind: 'href', value: '/semantic-models' },
    { kind: 'href', value: '/answers' },
    { kind: 'href', value: '/dashboards' },
    { kind: 'href', value: '/evaluation' },
    { kind: 'href', value: '/settings/models' },
    { kind: 'href', value: '/settings/security' },
    { kind: 'text', value: '退出登录' },
    { kind: 'text', value: '模型配置' },
    { kind: 'text', value: '成本与用量' },
    { kind: 'text', value: 'ONE_TRACE' },
    { kind: 'text', value: '模型治理' },
    { kind: 'text', value: '评测治理' },
  ];
  const stable = descriptors.map((descriptor, index) => {
    const candidates = controls.filter((item) => descriptor.kind === 'href'
      ? item.href === descriptor.value
      : item.control_text === descriptor.value);
    expect(candidates, `prior ONE_TRACE control ${descriptor.kind}=${descriptor.value}`).toHaveLength(1);
    return { ...candidates[0], target_case: `PRIOR_ONE_TRACE_${String(index + 1).padStart(2, '0')}` };
  });
  const trace = controls.find((item) => item.resource_type === 'TRACE'
    || item.logical_key === 'declared:governance.trace.open-detail');
  expect(trace, 'logical TRACE row control').toBeTruthy();
  const dynamicTraceCases = Array.from({ length: 26 }, (_item, index) => ({
    ...trace!,
    control_id: `CTL-T40-TRACE-${String(index + 1).padStart(2, '0')}-${trace!.logical_control_id?.slice(-6) ?? 'logical'}`,
    logical_control_id: trace!.logical_control_id ?? trace!.control_id,
    resource_type: 'TRACE',
    resource_id: null,
    target_case: `PRIOR_ONE_TRACE_${String(index + 15).padStart(2, '0')}`,
  }));
  const result = [...stable, ...dynamicTraceCases];
  expect(result, 'exact prior ONE_TRACE 40 case slots').toHaveLength(40);
  return result;
}

test('Phase5 control certification runner emits one real receipt per actionable control', async ({ page }, testInfo) => {
  test.setTimeout(3_600_000);
  const request = page.context().request;
  const inventory = JSON.parse(readFileSync(inventoryPath, 'utf8')) as Inventory;
  const identityCounts = new Map<string, number>();
  for (const control of inventory.controls) {
    const key = [control.page, control.route, control.tag, control.role, control.control_text, control.href ?? '', control.aria_label ?? ''].join('|');
    control.identity_ordinal = identityCounts.get(key) ?? 0;
    identityCounts.set(key, control.identity_ordinal + 1);
  }
  const allActionableControls = inventory.controls
    .filter((item) => item.enabled_state === 'ENABLED')
  expect(allActionableControls).toHaveLength(inventory.total_actionable_controls);
  const controls = targetSet === 'PRIOR_ONE_TRACE_40'
    ? previousOneTraceForty(inventory)
    : allActionableControls
      .filter((item) => requestedControlIds.size === 0 || requestedControlIds.has(item.control_id))
      .sort((left, right) => executionRank(left) - executionRank(right) || left.route.localeCompare(right.route) || left.selector_index - right.selector_index);
  if (requestedControlIds.size) expect(controls).toHaveLength(requestedControlIds.size);
  expect(new Set(controls.map((item) => item.control_id)).size).toBe(controls.length);

  await ensureAuthenticated(page);
  const me = await responseJson(await request.get(`${apiBase}/auth/me`));
  const workspaceId = String(me.user.workspace_id);
  const userId = String(me.user.id);
  const fixtureManager = new DynamicResourceFixtureManager(request, workspaceId, userId);
  let activeEvents: NetworkEvent[] | null = null;
  page.on('response', (response) => {
    if (!activeEvents) return;
    const requestItem = response.request();
    if (!new URL(response.url()).pathname.startsWith('/api/')) return;
    activeEvents.push({ method: requestItem.method(), path: safePath(response.url()), status: response.status() });
  });

  const receipts: ControlReceipt[] = [];
  for (const [index, inventoryControl] of controls.entries()) {
    await test.step(`${index + 1}/${controls.length} ${inventoryControl.control_id} ${inventoryControl.page} ${inventoryControl.control_text}`, async () => {
      let control = inventoryControl;
      const group = mutationGroup(control);
      const notApplicable = {
        status: 'NOT_APPLICABLE_WITH_EXPLICIT_REASON' as const,
        reason: 'The control is a read-only navigation, filter, selection, local UI state, clipboard or download action.',
      };
      const receipt: ControlReceipt = {
        SCHEMA_VERSION: 'chatbi.v13.phase5.control-receipt.v2',
        CONTROL_ID: control.control_id,
        LOGICAL_CONTROL_ID: control.logical_control_id ?? control.control_id,
        DOM_INSTANCE_COUNT: control.dom_instance_count ?? 1,
        PAGE: control.page,
        ROUTE: control.route,
        ROLE: 'ADMIN',
        TYPE: control.control_type,
        LOCATOR: control.locator,
        VISIBLE: false,
        ENABLED: false,
        ACTION: control.action,
        EXPECTED_RESULT: 'UNSET',
        NETWORK_REQUEST: [],
        HTTP_STATUS: [],
        DB_EFFECT_TYPE: group ? `APPLICABLE_${group.toUpperCase()}_PERSISTENCE` : 'NOT_APPLICABLE_WITH_EXPLICIT_REASON',
        DB_BEFORE: group ? null : notApplicable,
        DB_AFTER: group ? null : notApplicable,
        API_READBACK: [],
        NETWORK_API: { status: 'APPLICABLE', reason: 'Pending control execution evidence.' },
        REFRESH_RESULT: {},
        FINAL_STATUS: 'FAIL',
        FAIL_REASON: null,
        EVIDENCE: { inventory_sha256: inventory.inventory_sha256 },
        PAID_PROVIDER_CALLS: 0,
        PAID_PROVIDER_COST_CNY: 0,
      };
      let cleanup: (() => Promise<void>) | undefined;
      let dynamicFixture: DynamicTraceFixture | undefined;
      try {
        if (control.resource_type === 'TRACE') {
          dynamicFixture = await fixtureManager.create('TRACE', control.target_case ?? control.control_id);
          control = fixtureManager.bind(control, dynamicFixture);
          receipt.LOCATOR = control.locator;
          receipt.DB_BEFORE = dynamicFixture.db_before;
          receipt.DB_AFTER = dynamicFixture.db_after_create;
          receipt.EVIDENCE.dynamic_resource_fixture = {
            resource_id: dynamicFixture.resource_id,
            resource_type: dynamicFixture.resource_type,
            created_at: dynamicFixture.created_at,
            owning_workspace: dynamicFixture.owning_workspace,
            owning_user: dynamicFixture.owning_user,
            provider: dynamicFixture.provider,
            create_api_statuses: dynamicFixture.create_api_statuses,
          };
        }
        await preparePage(page, request, control);
        const locator = await locateControl(page, control);
        receipt.VISIBLE = await locator.isVisible();
        receipt.ENABLED = await locator.isEnabled();
        const beforeDom = await domReceipt(page);
        if (group && !dynamicFixture) receipt.DB_BEFORE = dbSnapshot(group, workspaceId);
        activeEvents = [];
        const action = await performAction(page, control, locator, testInfo);
        cleanup = action.cleanup;
        await page.waitForTimeout(200);
        const afterDom = await domReceipt(page);
        const events = activeEvents;
        activeEvents = null;
        const networkRequests = [...new Set(events.map((item) => `${item.method} ${item.path}`))];
        receipt.NETWORK_REQUEST = networkRequests;
        receipt.HTTP_STATUS = [...new Set(events.flatMap((item) => item.status === null ? [] : [item.status]))].sort((a, b) => a - b);
        receipt.EXPECTED_RESULT = action.expectedResult;
        if (group && !dynamicFixture) {
          receipt.DB_AFTER = dbSnapshot(group, workspaceId);
          expect((receipt.DB_BEFORE as DbSnapshot).fingerprint, `${control.control_id} DB state changed`).not.toBe((receipt.DB_AFTER as DbSnapshot).fingerprint);
        } else if (dynamicFixture) {
          expect((receipt.DB_BEFORE as DbSnapshot).fingerprint, `${control.control_id} trace fixture DB state changed`)
            .not.toBe((receipt.DB_AFTER as DbSnapshot).fingerprint);
        }
        const apiReads = await apiReadback(request, control);
        receipt.API_READBACK = apiReads;
        const pureUiNotApplicable: ExplicitNotApplicable = {
          status: 'NOT_APPLICABLE_WITH_EXPLICIT_REASON',
          reason: 'This read-only or local UI control has no Backend API contract; DOM, URL or browser-local state is the acceptance source.',
        };
        if (!group && networkRequests.length === 0) receipt.NETWORK_REQUEST = pureUiNotApplicable;
        if (!group && apiReads.length === 0) receipt.API_READBACK = pureUiNotApplicable;
        const networkApplicable = Array.isArray(receipt.NETWORK_REQUEST);
        const apiApplicable = Array.isArray(receipt.API_READBACK);
        receipt.NETWORK_API = networkApplicable || apiApplicable
          ? { status: 'APPLICABLE', reason: 'Network request or API readback evidence is attached.' }
          : { status: 'NOT_APPLICABLE_WITH_EXPLICIT_REASON', reason: pureUiNotApplicable.reason };
        const observableTransition = beforeDom.url !== afterDom.url
          || beforeDom.html_sha256 !== afterDom.html_sha256
          || networkRequests.length > 0
          || action.expectedResult === 'ACTIVE_CONTROL_IDEMPOTENT'
          || action.expectedResult === 'ROUTE_NAVIGATION_MATCHES_HREF'
          || action.expectedResult === 'INPUT_VALUE_ACCEPTED_AND_UI_REACTED'
          || action.expectedResult === 'FILTER_OR_SELECTION_APPLIED'
          || action.expectedResult === 'SINGLE_AVAILABLE_OPTION_CONFIRMED'
          || action.expectedResult === 'NEW_CONVERSATION_COMPOSER_READY'
          || action.expectedResult === 'FILTER_RESET_CONFIRMED'
          || action.expectedResult === 'EVIDENCE_DRAWER_VISIBLE'
          || action.expectedResult === 'DOCUMENT_FULLSCREEN_ACTIVE'
          || action.expectedResult === 'DASHBOARD_REFRESH_API_UI'
          || action.expectedResult.includes('CLIPBOARD')
          || action.expectedResult.includes('DOWNLOAD');
        expect(observableTransition, `${control.control_id} no observable result`).toBe(true);

        let refreshResponse: Awaited<ReturnType<Page['reload']>> | null = null;
        if (!page.isClosed()) {
          refreshResponse = await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => null);
          await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => undefined);
        }
        const refreshDom = page.isClosed() ? {} : await domReceipt(page);
        receipt.REFRESH_RESULT = {
          status: refreshResponse === null ? 'NO_DOCUMENT_RELOAD' : refreshResponse.status() < 400 ? 'PASS' : 'FAIL',
          http_status: refreshResponse?.status() ?? null,
          url: page.isClosed() ? null : page.url(),
          ui_sha256: refreshDom.html_sha256 ?? null,
          db_after_refresh: group ? dbSnapshot(group, workspaceId) : notApplicable,
          api_readback_after_refresh: group ? await apiReadback(request, control) : notApplicable,
        };
        if (refreshResponse) expect(refreshResponse.status()).toBeLessThan(400);
        if (group) {
          expect((receipt.REFRESH_RESULT.db_after_refresh as DbSnapshot).fingerprint)
            .toBe((receipt.DB_AFTER as DbSnapshot).fingerprint);
        }
        receipt.EVIDENCE = {
          ...receipt.EVIDENCE,
          before_dom: beforeDom,
          after_dom: afterDom,
          action_observable: action.observable,
          network_event_count: events.length,
        };
        if (dynamicFixture) {
          const fixtureToCleanup = dynamicFixture;
          dynamicFixture = undefined;
          const cleanupEvidence = await fixtureManager.cleanup(fixtureToCleanup);
          receipt.EVIDENCE.dynamic_resource_fixture = {
            ...(receipt.EVIDENCE.dynamic_resource_fixture as Record<string, unknown>),
            cleanup: cleanupEvidence,
          };
        }
        receipt.FINAL_STATUS = 'PASS';
      } catch (error) {
        activeEvents = null;
        receipt.FAIL_REASON = error instanceof Error ? error.message : String(error);
        receipt.FINAL_STATUS = 'FAIL';
      } finally {
        if (cleanup) await cleanup().catch(() => undefined);
        if (dynamicFixture) {
          try {
            const cleanupEvidence = await fixtureManager.cleanup(dynamicFixture);
            receipt.EVIDENCE.dynamic_resource_fixture = {
              ...(receipt.EVIDENCE.dynamic_resource_fixture as Record<string, unknown>),
              cleanup: cleanupEvidence,
            };
          } catch (cleanupError) {
            const message = cleanupError instanceof Error ? cleanupError.message : String(cleanupError);
            receipt.FAIL_REASON = [receipt.FAIL_REASON, `DYNAMIC_RESOURCE_CLEANUP_FAILED:${message}`].filter(Boolean).join('; ');
            receipt.FINAL_STATUS = 'FAIL';
          }
        }
        if (control.page.startsWith('问数据')) await ensureAuthenticated(page).then(() => resetChatFixtures(request)).catch(() => undefined);
        if (control.control_text === '退出登录') await ensureAuthenticated(page).catch(() => undefined);
        const receiptPath = resolve(outputRoot, 'receipts', `${control.control_id}.json`);
        atomicJson(receiptPath, receipt);
        receipts.push(receipt);
      }
    });
  }

  const failed = receipts.filter((item) => item.FINAL_STATUS !== 'PASS');
  const noops = receipts.filter((item) => item.FINAL_STATUS === 'PASS'
    && item.EXPECTED_RESULT === 'OBSERVABLE_UI_NETWORK_OR_STATE_TRANSITION'
    && Number(item.EVIDENCE.network_event_count ?? 0) === 0
    && (item.EVIDENCE.before_dom as any)?.html_sha256 === (item.EVIDENCE.after_dom as any)?.html_sha256);
  const mutationReceipts = receipts.filter((item) => item.DB_EFFECT_TYPE.startsWith('APPLICABLE_'));
  const refreshPassed = receipts.filter((item) => item.REFRESH_RESULT.status === 'PASS').length;
  const serializedReceipts = JSON.stringify(receipts.map((item) => ({ id: item.CONTROL_ID, status: item.FINAL_STATUS })));
  const incompleteEvidence = receipts.filter((item) => item.FINAL_STATUS === 'PASS' && (
    (Array.isArray(item.NETWORK_REQUEST) && item.NETWORK_REQUEST.length === 0)
    || (Array.isArray(item.API_READBACK) && item.API_READBACK.length === 0)
    || item.NETWORK_API.reason.length === 0
  ));
  const manifest = {
    schema_version: 'chatbi.v13.phase5.control-certification-manifest.v2',
    status: failed.length === 0 && noops.length === 0 && incompleteEvidence.length === 0 ? 'PASS' : 'FAIL',
    inventory_sha256: inventory.inventory_sha256,
    control_inventory_schema_version: inventory.schema_version ?? null,
    control_discovery_rule_hash: inventory.control_discovery_rule_hash ?? null,
    certification_scope: targetSet || requestedControlIds.size ? 'TARGETED_PREFLIGHT' : 'FULL_INVENTORY',
    target_set: targetSet || null,
    total_visible_controls: inventory.total_visible_controls,
    total_actionable_controls: controls.length,
    total_tested_controls: receipts.length,
    visible_actionable_control_coverage: receipts.length / controls.length,
    applicable_control_pass_rate: mutationReceipts.length
      ? mutationReceipts.filter((item) => item.FINAL_STATUS === 'PASS').length / mutationReceipts.length
      : 1,
    noop_control_count: noops.length,
    broken_control_count: failed.length,
    fake_success_count: incompleteEvidence.length,
    trace_control_stale_id_failures: failed.filter((item) => item.TYPE === 'BUTTON'
      && item.ROUTE === '/settings/models?view=trace').length,
    dynamic_resource_fixture_manager: {
      supported_resource_types: DynamicResourceFixtureManager.supportedResourceTypes,
      exercised_resource_types: receipts.some((item) => (
        (item.EVIDENCE.dynamic_resource_fixture as any)?.resource_type === 'TRACE'
      )) ? ['TRACE'] : [],
    },
    db_persistence_gate: mutationReceipts.every((item) => item.FINAL_STATUS === 'PASS') ? 'PASS' : 'FAIL',
    refresh_persistence_rate: receipts.length ? refreshPassed / receipts.length : 0,
    control_matrix_paid_provider_calls: 0,
    paid_provider_cost_cny: 0,
    failed_control_ids: failed.map((item) => item.CONTROL_ID),
    noop_control_ids: noops.map((item) => item.CONTROL_ID),
    incomplete_evidence_control_ids: incompleteEvidence.map((item) => item.CONTROL_ID),
    receipts_sha256: sha256(serializedReceipts),
  };
  atomicJson(resolve(outputRoot, 'control-certification-manifest.json'), manifest);
  expect(manifest.total_tested_controls).toBe(manifest.total_actionable_controls);
  expect(manifest.visible_actionable_control_coverage).toBe(1);
  expect(manifest.applicable_control_pass_rate).toBe(1);
  expect(manifest.noop_control_count).toBe(0);
  expect(manifest.broken_control_count).toBe(0);
  expect(manifest.fake_success_count).toBe(0);
  expect(manifest.db_persistence_gate).toBe('PASS');
  expect(manifest.refresh_persistence_rate).toBe(1);
});
