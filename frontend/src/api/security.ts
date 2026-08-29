import { api } from './client';
import type {
  AuditPage, PermissionResourceType, ResourcePermission, SecurityOverview, SecurityUser,
  WorkspaceInvitation,
} from '../types/api';

export const securityApi = {
  overview: (options: { query?: string; status?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.query) params.set('user_query', options.query);
    if (options.status && options.status !== 'ALL') params.set('user_status', options.status);
    const suffix = params.toString();
    return api<SecurityOverview>(`/security/overview${suffix ? `?${suffix}` : ''}`).then((value) => ({
      ...value,
      permission_resources: value.permission_resources ?? [],
      resource_grants: value.resource_grants ?? [],
    }));
  },
  createUser: (body: { email: string; display_name: string; role: string; password: string }) => api<SecurityUser>('/security/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: string, body: { role?: string; status?: string }) => api<SecurityUser>(`/security/users/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  removeUser: (id: string) => api<void>(`/security/users/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  resourcePermissions: (userId: string) => api<ResourcePermission[]>(`/security/users/${encodeURIComponent(userId)}/resource-permissions`),
  setResourcePermission: (
    userId: string,
    resourceType: PermissionResourceType,
    resourceId: string,
    body: { can_read: boolean; can_query: boolean },
  ) => api<ResourcePermission>(
    `/security/users/${encodeURIComponent(userId)}/resource-permissions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`,
    { method: 'PUT', body: JSON.stringify(body) },
  ),
  revokeResourcePermission: (userId: string, resourceType: PermissionResourceType, resourceId: string) => api<void>(
    `/security/users/${encodeURIComponent(userId)}/resource-permissions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`,
    { method: 'DELETE' },
  ),
  invite: (body: { email: string; role: string; expires_in_days: number }) => api<WorkspaceInvitation>(`/security/invitations`, { method: 'POST', body: JSON.stringify(body) }),
  revokeInvite: (id: string) => api<WorkspaceInvitation>(`/security/invitations/${encodeURIComponent(id)}/revoke`, { method: 'POST' }),
  audit: (options: { query?: string; action?: string; actor?: string; resource?: string; event_status?: string; start_at?: string; end_at?: string; page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(options).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)); });
    return api<AuditPage>(`/security/audit?${params.toString()}`);
  },
};
