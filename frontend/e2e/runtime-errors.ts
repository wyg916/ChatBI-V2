import type { Page } from '@playwright/test';

export function captureRuntimeErrors(page: Page, expectedHttpStatuses: number[] = []) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const blockingRequestErrors: string[] = [];
  page.on('console', (message) => {
    const text = message.text();
    const expectedRejection = expectedHttpStatuses.some((status) =>
      text.includes(`status of ${status}`) || text.includes(`${status} (`),
    );
    if (message.type() === 'error' && !expectedRejection) consoleErrors.push(text);
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    const reason = request.failure()?.errorText ?? '';
    if (!reason.includes('ERR_ABORTED') && !reason.includes('NS_BINDING_ABORTED')) {
      blockingRequestErrors.push(`${request.url()}:${reason}`);
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400 && !expectedHttpStatuses.includes(response.status())) {
      blockingRequestErrors.push(`${response.status()} ${response.url()}`);
    }
  });
  return { consoleErrors, pageErrors, blockingRequestErrors };
}
