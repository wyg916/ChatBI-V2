import { expect, test } from '@playwright/test';

import {
  verifyRefreshPersistence,
  type PersistenceSnapshot,
} from './support/refresh-persistence';

function snapshot(
  fingerprint: string,
  rowCount: number,
  stateDigest: string,
  identityDigests: string[],
): PersistenceSnapshot {
  return {
    fingerprint,
    tables: {
      record: {
        status: 'PRESENT',
        row_count: rowCount,
        state_digest: stateDigest,
        identity_digests: identityDigests,
      },
    },
  };
}

test('Phase5 refresh persistence distinguishes exact state from safe async convergence', () => {
  const before = snapshot('before', 1, 'state-1', ['id-1']);
  const after = snapshot('after', 2, 'state-2', ['id-1', 'id-2']);

  expect(verifyRefreshPersistence('semantic', before, after, after).mode).toBe('EXACT_STATE');
  expect(() => verifyRefreshPersistence(
    'semantic', before, after, snapshot('drift', 2, 'state-3', ['id-1', 'id-2']),
  )).toThrow('REFRESH_PERSISTENCE_EXACT_STATE_MISMATCH');

  const chatRefresh = snapshot('chat-refresh', 3, 'state-3', ['id-1', 'id-2', 'id-3']);
  expect(verifyRefreshPersistence('chat', before, after, chatRefresh).mode)
    .toBe('MONOTONIC_IDENTITY_WITH_ASYNC_CONVERGENCE');
  expect(verifyRefreshPersistence(
    'evaluation', before, after, snapshot('terminal', 2, 'completed', ['id-1', 'id-2']),
  ).status).toBe('PASS');

  expect(() => verifyRefreshPersistence(
    'chat', before, after, snapshot('loss', 2, 'state-3', ['id-1', 'id-3']),
  )).toThrow('REFRESH_PERSISTENCE_IDENTITY_LOSS:record:1');
  expect(() => verifyRefreshPersistence(
    'chat', before, after, snapshot('decrease', 1, 'state-3', ['id-1']),
  )).toThrow('REFRESH_PERSISTENCE_ROW_COUNT_DECREASED:record');
});
