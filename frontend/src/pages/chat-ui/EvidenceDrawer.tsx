import { type RefObject, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export interface PublicCitation {
  id: string;
  title: string;
  version: string;
  locator: string;
}

export interface EvidenceDrawerData {
  dataAndSemantics: Array<{ label: string; value: string }>;
  sql?: string;
  businessEvidence: PublicCitation[];
  phases: string[];
  verification: string[];
}

interface EvidenceDrawerProps {
  data: EvidenceDrawerData;
  onClose: () => void;
  returnFocusRef: RefObject<HTMLButtonElement>;
}

export function EvidenceDrawer({ data, onClose, returnFocusRef }: EvidenceDrawerProps) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const backdrop = backdropRef.current;
    const backgroundStates = Array.from(document.body.children)
      .filter((node): node is HTMLElement => node instanceof HTMLElement && Boolean(backdrop) && !node.contains(backdrop))
      .map((node) => ({ node, inert: node.hasAttribute('inert'), ariaHidden: node.getAttribute('aria-hidden') }));
    backgroundStates.forEach(({ node }) => {
      node.setAttribute('inert', '');
      node.setAttribute('aria-hidden', 'true');
    });
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const drawer = drawerRef.current;
      if (!drawer) return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
      )).filter((node) => !node.hasAttribute('hidden') && node.getAttribute('aria-hidden') !== 'true');
      const first = focusable[0] ?? closeRef.current;
      const last = focusable.at(-1) ?? closeRef.current;
      if (!first || !last) return;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !drawer.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !drawer.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      document.body.style.overflow = previousBodyOverflow;
      backgroundStates.forEach(({ node, inert, ariaHidden }) => {
        if (!inert) node.removeAttribute('inert');
        if (ariaHidden === null) node.removeAttribute('aria-hidden');
        else node.setAttribute('aria-hidden', ariaHidden);
      });
      const target = returnFocusRef.current ?? previousFocusRef.current;
      target?.focus();
    };
  }, [returnFocusRef]);

  return createPortal(
    <div ref={backdropRef} className="evidence-drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside ref={drawerRef} className="evidence-drawer" role="dialog" aria-modal="true" aria-label="SQL 与执行明细" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><span>可核验信息</span><h2 id="evidence-drawer-title">查询依据</h2></div>
          <button ref={closeRef} type="button" aria-label="关闭查询明细" onClick={onClose}>×</button>
        </header>

        <section>
          <h3>数据与口径</h3>
          <dl className="evidence-definition-list">
            {data.dataAndSemantics.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
          </dl>
        </section>

        <section>
          <h3>SQL</h3>
          {data.sql ? <pre><code>{data.sql}</code></pre> : <p className="evidence-empty">本次回答没有可公开的 SQL。</p>}
        </section>

        <section>
          <h3>业务依据</h3>
          {data.businessEvidence.length > 0 ? data.businessEvidence.map((citation) => (
            <article className="drawer-citation" key={citation.id}>
              <strong>{citation.title}</strong>
              <small>版本 {citation.version} · {citation.locator}</small>
            </article>
          )) : <p className="evidence-empty">本次回答未使用额外业务文档。</p>}
        </section>

        <section>
          <h3>分析过程</h3>
          <ol className="public-phase-list">
            {data.phases.map((phase) => <li key={phase}>{phase}</li>)}
          </ol>
          {data.verification.map((item) => <p className="verification-line" key={item}>✓ {item}</p>)}
        </section>
      </aside>
    </div>,
    document.body,
  );
}
