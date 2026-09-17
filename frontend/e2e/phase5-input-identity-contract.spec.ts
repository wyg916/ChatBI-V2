import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

import {
  CONTROL_SELECTOR,
  locatorIdentityKey,
  logicalControlId,
  logicalInputKey,
  visibleControlCandidates,
  type LocatorIdentity,
} from './support/control-identity';

const evidencePath = process.env.CHATBI_PHASE5_INPUT_IDENTITY_EVIDENCE;

const fixture = `
  <main>
    <form aria-label="identity-form-a">
      <label>空输入<input data-case="empty" /></label>
      <label>已输入<input data-case="typed" value="typed-before-scan" /></label>
      <label>已清空<input data-case="cleared" value="" /></label>
      <label>预填输入<input data-case="prefilled" value="prefilled-value" /></label>
      <label>密码<input data-case="password" type="password" name="password" value="secret-not-identity" /></label>
      <label>搜索<input data-case="search" type="search" aria-label="搜索合同" value="mutable-search" /></label>
      <input data-case="duplicate-empty-a" />
      <input data-case="duplicate-empty-b" />
      <label>动态占位<input data-case="dynamic-placeholder" name="dynamic-query" placeholder="占位版本一" /></label>
      <label>禁用输入<input data-case="disabled" disabled /></label>
      <label>电子邮箱<input data-case="email" type="email" /></label>
      <label>数字<input data-case="number" type="number" /></label>
      <label>日期<input data-case="date" type="date" /></label>
      <label>日期时间<input data-case="datetime" type="datetime-local" /></label>
      <label>月份<input data-case="month" type="month" /></label>
      <label>时间<input data-case="time" type="time" /></label>
      <label>网址<input data-case="url" type="url" /></label>
      <label>电话<input data-case="tel" type="tel" /></label>
      <label for="labelled-input">显式标签</label><input data-case="labelled" id="labelled-input" />
      <span id="aria-label-source">ARIA 引用标签</span><input data-case="aria-labelledby" aria-labelledby="aria-label-source" />
      <textarea data-case="textarea" name="notes">mutable textarea text</textarea>
      <div data-case="contenteditable" contenteditable="true" aria-label="可编辑说明">mutable editable text</div>
    </form>
    <form aria-label="identity-form-b"><input data-case="same-placeholder-form-b" placeholder="同名搜索" /></form>
    <form aria-label="identity-form-c"><input data-case="same-placeholder-form-c" placeholder="同名搜索" /></form>
  </main>
`;

type Snapshot = Record<string, { logicalId: string; identity: LocatorIdentity }>;

async function snapshot(page: Page): Promise<Snapshot> {
  const candidates = (await visibleControlCandidates(page)).filter((item) => item.control_type === 'INPUT');
  const result: Snapshot = {};
  for (const candidate of candidates) {
    const caseId = await page.locator(CONTROL_SELECTOR).nth(candidate.selector_index).getAttribute('data-case');
    expect(caseId, `input at selector index ${candidate.selector_index} requires a regression case id`).toBeTruthy();
    result[caseId!] = {
      logicalId: logicalControlId('/identity-contract', 'BASE_PAGE', 'ADMIN', logicalInputKey(candidate)),
      identity: candidate.locator_identity,
    };
  }
  return result;
}

async function mutateValues(page: Page, mode: 'typed' | 'cleared') {
  await page.locator('[data-case]').evaluateAll((elements, mutationMode) => {
    for (const node of elements as HTMLElement[]) {
      if (node.getAttribute('data-case') === 'disabled') continue;
      if (node.isContentEditable) {
        node.textContent = mutationMode === 'typed' ? 'changed editable value' : '';
        node.dispatchEvent(new InputEvent('input', { bubbles: true }));
        continue;
      }
      const input = node as HTMLInputElement | HTMLTextAreaElement;
      if (!('value' in input)) continue;
      if (mutationMode === 'cleared') input.value = '';
      else if (input instanceof HTMLInputElement) {
        const values: Record<string, string> = {
          date: '2026-08-25',
          'datetime-local': '2026-08-25T08:30',
          month: '2026-08',
          time: '08:30',
          number: '42',
          email: 'user@example.test',
          url: 'https://example.test',
        };
        input.value = values[input.type] ?? 'changed mutable value';
      } else input.value = 'changed textarea value';
      input.dispatchEvent(new InputEvent('input', { bubbles: true }));
    }
    const dynamic = document.querySelector<HTMLInputElement>('[data-case="dynamic-placeholder"]');
    if (dynamic) dynamic.placeholder = mutationMode === 'typed' ? '占位版本二' : '占位版本三';
  }, mode);
}

function expectStable(reference: Snapshot, current: Snapshot, stage: string) {
  expect(Object.keys(current).sort(), `${stage} case universe`).toEqual(Object.keys(reference).sort());
  for (const [caseId, expected] of Object.entries(reference)) {
    expect(current[caseId].logicalId, `${caseId} logical id after ${stage}`).toBe(expected.logicalId);
    expect(locatorIdentityKey(current[caseId].identity), `${caseId} locator identity after ${stage}`)
      .toBe(locatorIdentityKey(expected.identity));
    expect(current[caseId].identity.mutable_value_used, `${caseId} mutable value exclusion`).toBe(false);
  }
}

test('Phase5 input identity remains stable across value and DOM lifecycle changes', async ({ page }) => {
  await page.setContent(fixture);
  const empty = await snapshot(page);
  expect(Object.keys(empty)).toHaveLength(24);
  expect(new Set(Object.values(empty).map((item) => item.logicalId)).size, 'every scoped fixture is one logical control')
    .toBe(24);

  await mutateValues(page, 'typed');
  const typed = await snapshot(page);
  expectStable(empty, typed, 'typed');

  await mutateValues(page, 'cleared');
  const cleared = await snapshot(page);
  expectStable(empty, cleared, 'cleared');

  await page.setContent(fixture);
  const reacquired = await snapshot(page);
  expectStable(empty, reacquired, 'DOM reacquisition');

  const currentCandidates = (await visibleControlCandidates(page)).filter((item) => item.control_type === 'INPUT');
  for (const [caseId, expected] of Object.entries(empty)) {
    const matches = currentCandidates.filter((candidate) => (
      locatorIdentityKey(candidate.locator_identity) === locatorIdentityKey(expected.identity)
    ));
    expect(matches, `${caseId} exact stable relocation candidate`).toHaveLength(1);
  }

  if (evidencePath) {
    const destination = resolve(evidencePath);
    mkdirSync(dirname(destination), { recursive: true });
    writeFileSync(destination, `${JSON.stringify({
      schema_version: 'chatbi.v13.phase5.input-identity-regression.v1',
      status: 'PASS',
      case_count: Object.keys(empty).length,
      lifecycle_stages: ['empty_or_prefilled', 'typed', 'cleared', 'DOM_reacquired'],
      stale_locator_failures: 0,
      non_unique_relocations: 0,
      mutable_value_identity_uses: 0,
      logical_ids: Object.fromEntries(Object.entries(empty).map(([key, value]) => [key, value.logicalId])),
    }, null, 2)}\n`, 'utf8');
  }
});
