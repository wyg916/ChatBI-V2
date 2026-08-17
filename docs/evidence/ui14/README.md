# UI14 Integration Acceptance Evidence

This directory records the repeatable acceptance contract for the existing 14-page React UI baseline. The integration task did not regenerate or redesign any page.

- `test-summary.json`: machine-readable result for route, viewport, runtime-error, Frontend and Day 1 regression gates.
- `frontend/e2e/ui14-integration.spec.ts`: executable source of truth for 14 direct URL routes across 1440x900, 1366x768 and 1920x1080.
- Each UI14 run captures 42 viewport screenshots (14 pages x 3 viewports) under ignored `frontend/test-results/`; Playwright also keeps an attachment copy for each image. These generated binaries are intentionally not committed.
- Direct URL navigation is asserted as HTTP 200 and a page-specific React marker must become visible. Every App Shell page must retain exactly six primary navigation links; system settings stays outside that primary navigation.
- The run fails on page-level horizontal clipping, a clipped or obstructed critical control, React/API error notices, console errors, page errors or failed browser requests.

The existing tracked Day 2 screenshot remains unchanged. Playwright now writes subsequent visual-run artifacts only to its ignored output directory so a regression run cannot dirty the Git worktree.
