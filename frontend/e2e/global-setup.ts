import { request, type FullConfig } from '@playwright/test';

const apiBase = process.env.CHATBI_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

export default async function globalSetup(_: FullConfig) {
  const api = await request.newContext();
  try {
    const sourceResponse = await api.get(`${apiBase}/datasources`);
    if (!sourceResponse.ok()) throw new Error(`Datasource fixture discovery failed: HTTP ${sourceResponse.status()}`);
    const sources = await sourceResponse.json() as Array<{ id: string; type: string }>;
    for (const dialect of ['postgresql', 'mysql']) {
      const source = sources.find((item) => item.type === dialect);
      if (!source) throw new Error(`Missing ${dialect} datasource fixture`);
      const connection = await api.post(`${apiBase}/datasources/${source.id}/test`);
      const connectionBody = await connection.json();
      if (!connection.ok() || !connectionBody.success) throw new Error(`${dialect} datasource fixture is not reachable`);
      const sync = await api.post(`${apiBase}/datasources/${source.id}/sync`);
      const syncBody = await sync.json();
      if (!sync.ok() || !syncBody.success) throw new Error(`${dialect} metadata fixture sync failed`);
      const schemas = await api.get(`${apiBase}/datasources/${source.id}/schemas`);
      const schemaBody = await schemas.json();
      if (!schemas.ok() || !Array.isArray(schemaBody) || schemaBody.length === 0) {
        throw new Error(`${dialect} metadata fixture is empty after synchronization`);
      }
    }
  } finally {
    await api.dispose();
  }
}
