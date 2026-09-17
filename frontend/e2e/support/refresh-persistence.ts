export type PersistenceTableSnapshot = {
  status: string;
  row_count?: number;
  state_digest?: string;
  identity_digests?: string[];
};

export type PersistenceSnapshot = {
  fingerprint: string;
  tables: Record<string, PersistenceTableSnapshot>;
};

export type RefreshPersistenceEvidence = {
  status: 'PASS';
  mode: 'EXACT_STATE' | 'MONOTONIC_IDENTITY_WITH_ASYNC_CONVERGENCE';
  changed_tables: string[];
  verified_tables: string[];
  missing_identity_digests: 0;
};

const ASYNC_CONVERGENT_GROUPS = new Set(['chat', 'evaluation']);

function changedTables(before: PersistenceSnapshot, after: PersistenceSnapshot): string[] {
  return Object.keys(after.tables).filter((table) => {
    const left = before.tables[table];
    const right = after.tables[table];
    return left?.row_count !== right?.row_count || left?.state_digest !== right?.state_digest;
  });
}

export function verifyRefreshPersistence(
  group: string,
  before: PersistenceSnapshot,
  after: PersistenceSnapshot,
  refreshed: PersistenceSnapshot,
): RefreshPersistenceEvidence {
  const changed = changedTables(before, after);
  if (changed.length === 0) throw new Error('REFRESH_PERSISTENCE_NO_MUTATION_TO_VERIFY');

  if (!ASYNC_CONVERGENT_GROUPS.has(group)) {
    if (after.fingerprint !== refreshed.fingerprint) {
      throw new Error('REFRESH_PERSISTENCE_EXACT_STATE_MISMATCH');
    }
    return {
      status: 'PASS',
      mode: 'EXACT_STATE',
      changed_tables: changed,
      verified_tables: Object.keys(after.tables),
      missing_identity_digests: 0,
    };
  }

  const verified: string[] = [];
  for (const [table, afterTable] of Object.entries(after.tables)) {
    if (afterTable.status !== 'PRESENT') continue;
    const refreshedTable = refreshed.tables[table];
    if (!refreshedTable || refreshedTable.status !== 'PRESENT') {
      throw new Error(`REFRESH_PERSISTENCE_TABLE_MISSING:${table}`);
    }
    const afterCount = afterTable.row_count ?? 0;
    const refreshedCount = refreshedTable.row_count ?? 0;
    if (refreshedCount < afterCount) {
      throw new Error(`REFRESH_PERSISTENCE_ROW_COUNT_DECREASED:${table}`);
    }
    const refreshedIdentities = new Set(refreshedTable.identity_digests ?? []);
    const missing = (afterTable.identity_digests ?? []).filter((identity) => !refreshedIdentities.has(identity));
    if (missing.length > 0) {
      throw new Error(`REFRESH_PERSISTENCE_IDENTITY_LOSS:${table}:${missing.length}`);
    }
    verified.push(table);
  }
  return {
    status: 'PASS',
    mode: 'MONOTONIC_IDENTITY_WITH_ASYNC_CONVERGENCE',
    changed_tables: changed,
    verified_tables: verified,
    missing_identity_digests: 0,
  };
}
