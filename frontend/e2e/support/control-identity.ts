import { createHash } from 'node:crypto';

import type { Page } from '@playwright/test';

export const CONTROL_SELECTOR = [
  'button', 'a[href]', 'input:not([type="hidden"])', 'textarea', 'select',
  '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
  '[role="switch"]', '[role="checkbox"]', '[role="radio"]', '[contenteditable="true"]',
].join(',');

export type LocatorIdentity = {
  version: 'chatbi.control-locator-identity.v1';
  tag: string;
  role: string;
  input_type: string;
  key_kind: 'DATA_TESTID' | 'ID' | 'HREF' | 'NAME' | 'ARIA_LABEL' | 'ARIA_LABELLEDBY' | 'PLACEHOLDER' | 'FIELD_SEMANTIC' | 'CONTROL_TEXT' | 'STRUCTURAL';
  key_value: string;
  form_identity: string;
  container_identity: string;
  stable_scope: string;
  stable_ordinal: number;
  mutable_value_used: false;
};

export type RawControlCandidate = {
  selector_index: number;
  tag: string;
  role: string;
  input_type: string;
  display_label: string;
  disabled: boolean;
  control_type: string;
  test_id: string | null;
  logical_control: string | null;
  resource_type: string | null;
  resource_id: string | null;
  href: string | null;
  id: string | null;
  name: string | null;
  aria_label: string | null;
  aria_labelledby: string | null;
  placeholder: string | null;
  form_identity: string;
  container_identity: string;
  field_semantic_key: string;
  option_values: string[];
  style_visible: boolean;
};

export type IdentityCandidate = RawControlCandidate & {
  locator_identity: LocatorIdentity;
};

function clean(value: string | null | undefined): string {
  return (value ?? '').replace(/\s+/g, ' ').trim().slice(0, 240);
}

function identityBase(candidate: RawControlCandidate): Omit<LocatorIdentity, 'stable_ordinal'> {
  const isInputLike = candidate.control_type === 'INPUT';
  const choices: Array<[LocatorIdentity['key_kind'], string]> = [
    ['DATA_TESTID', clean(candidate.test_id) && `${clean(candidate.test_id)}${candidate.href ? `|href:${clean(candidate.href)}` : ''}`],
    ['ID', clean(candidate.id)],
    ['HREF', clean(candidate.href)],
    ['NAME', clean(candidate.name)],
    ['ARIA_LABEL', clean(candidate.aria_label)],
    ['ARIA_LABELLEDBY', clean(candidate.aria_labelledby)],
    ['PLACEHOLDER', clean(candidate.placeholder)],
    ['FIELD_SEMANTIC', clean(candidate.field_semantic_key)],
    ['CONTROL_TEXT', isInputLike ? '' : clean(candidate.display_label)],
    ['STRUCTURAL', `${candidate.tag}:${candidate.input_type || 'none'}`],
  ];
  const [keyKind, keyValue] = choices.find(([, value]) => value.length > 0) ?? choices.at(-1)!;
  const formIdentity = clean(candidate.form_identity);
  const containerIdentity = clean(candidate.container_identity);
  const globalIdentity = ['DATA_TESTID', 'ID', 'HREF'].includes(keyKind);
  const stableScope = globalIdentity
    ? 'GLOBAL'
    : [formIdentity || 'NO_FORM', containerIdentity || 'NO_CONTAINER'].join('::');
  return {
    version: 'chatbi.control-locator-identity.v1',
    tag: candidate.tag,
    role: candidate.role,
    input_type: candidate.input_type,
    key_kind: keyKind,
    key_value: keyValue,
    form_identity: formIdentity,
    container_identity: containerIdentity,
    stable_scope: stableScope,
    mutable_value_used: false,
  };
}

export function attachLocatorIdentities(candidates: RawControlCandidate[]): IdentityCandidate[] {
  const ordinals = new Map<string, number>();
  return candidates.map((candidate) => {
    const base = identityBase(candidate);
    const baseKey = JSON.stringify(base);
    const stableOrdinal = ordinals.get(baseKey) ?? 0;
    ordinals.set(baseKey, stableOrdinal + 1);
    return {
      ...candidate,
      locator_identity: { ...base, stable_ordinal: stableOrdinal },
    };
  });
}

export function locatorIdentityKey(identity: LocatorIdentity): string {
  return JSON.stringify(identity);
}

export function logicalInputKey(candidate: IdentityCandidate): string {
  return `input:${locatorIdentityKey(candidate.locator_identity)}`;
}

export function logicalStableKey(candidate: IdentityCandidate): string {
  return `${candidate.control_type.toLowerCase()}:${locatorIdentityKey(candidate.locator_identity)}`;
}

export function logicalControlId(route: string, surface: string, role: string, logicalKey: string): string {
  return `CTL-${createHash('sha256')
    .update(`${route}|${surface}|${role}|${logicalKey}`)
    .digest('hex')
    .slice(0, 16)}`;
}

export async function visibleControlCandidates(page: Page): Promise<IdentityCandidate[]> {
  const candidates = await page.locator(CONTROL_SELECTOR).evaluateAll((elements) => elements.map((element, index) => {
    const node = element as HTMLElement;
    const input = node as HTMLInputElement;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    const tag = node.tagName.toLowerCase();
    const role = node.getAttribute('role') ?? '';
    const inputType = tag === 'input' ? (input.type || 'text') : '';
    const isInputLike = tag === 'input' || tag === 'textarea' || node.isContentEditable;
    const stableText = (source: Element | null): string => {
      if (!source) return '';
      const clone = source.cloneNode(true) as HTMLElement;
      clone.querySelectorAll('input,textarea,select,button,[contenteditable="true"]').forEach((child) => child.remove());
      return (clone.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 240);
    };
    const labels = 'labels' in input && input.labels
      ? Array.from(input.labels).map((label) => stableText(label)).filter(Boolean)
      : [];
    const labelledBy = node.getAttribute('aria-labelledby');
    const labelledByText = labelledBy
      ? labelledBy.split(/\s+/).map((id) => stableText(document.getElementById(id))).filter(Boolean).join(' | ')
      : '';
    const fieldSemanticKey = [...labels, labelledByText].filter(Boolean).join(' | ');
    const form = node.closest('form');
    const formIdentity = form
      ? (
        form.getAttribute('data-testid')
        || form.id
        || form.getAttribute('name')
        || form.getAttribute('aria-label')
        || form.className
        || stableText(form.querySelector('legend,h1,h2,h3'))
        || 'FORM'
      )
      : '';
    const container = node.closest('label,fieldset,[data-control-scope],[data-testid]');
    const containerIdentity = container
      ? (
        container.getAttribute('data-control-scope')
        || container.getAttribute('data-testid')
        || container.id
        || stableText(container)
      )
      : '';
    const ariaLabel = node.getAttribute('aria-label');
    const title = node.getAttribute('title');
    const placeholder = input.placeholder || null;
    const displayLabel = (
      ariaLabel
      || title
      || (isInputLike ? fieldSemanticKey : node.textContent)
      || placeholder
      || node.getAttribute('name')
      || node.id
      || `[${tag}]`
    ).replace(/\s+/g, ' ').trim().slice(0, 240);
    const disabled = input.disabled || input.readOnly || node.getAttribute('aria-disabled') === 'true';
    let controlType = 'BUTTON';
    if (tag === 'a' || role === 'link') controlType = 'LINK_ACTION';
    else if (role === 'tab') controlType = 'TAB';
    else if (role === 'menuitem') controlType = 'MENU_ITEM';
    else if (tag === 'select') controlType = 'DROPDOWN_ACTION';
    else if (inputType === 'file') controlType = 'UPLOAD';
    else if (inputType === 'checkbox' || role === 'checkbox') controlType = 'CHECKBOX';
    else if (role === 'switch') controlType = 'TOGGLE';
    else if (inputType === 'radio' || role === 'radio') controlType = 'RADIO';
    else if (isInputLike) controlType = 'INPUT';
    else if (role === 'button' && tag !== 'button') controlType = 'ICON_BUTTON';
    return {
      selector_index: index,
      tag,
      role,
      input_type: inputType,
      display_label: displayLabel,
      disabled,
      control_type: controlType,
      test_id: node.dataset.testid ?? null,
      logical_control: node.dataset.logicalControl ?? null,
      resource_type: node.dataset.resourceType ?? null,
      resource_id: node.dataset.resourceId ?? null,
      href: node instanceof HTMLAnchorElement ? node.getAttribute('href') : null,
      id: node.id || null,
      name: node.getAttribute('name'),
      aria_label: ariaLabel,
      aria_labelledby: labelledBy,
      placeholder,
      form_identity: formIdentity,
      container_identity: containerIdentity,
      field_semantic_key: fieldSemanticKey,
      option_values: node instanceof HTMLSelectElement
        ? Array.from(node.options).map((option) => option.value)
        : [],
      style_visible: !(
        style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0
        || rect.width <= 0 || rect.height <= 0
      ),
    } satisfies RawControlCandidate;
  }));
  const playwrightVisibility = await Promise.all(
    candidates.map((item) => page.locator(CONTROL_SELECTOR).nth(item.selector_index).isVisible()),
  );
  return attachLocatorIdentities(
    candidates.filter((item, index) => item.style_visible && playwrightVisibility[index]),
  );
}
