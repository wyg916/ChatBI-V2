const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? body.message ?? `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function unwrapList<T>(value: T[] | { items: T[] }): T[] {
  return Array.isArray(value) ? value : value.items;
}
