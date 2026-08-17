import { api } from './client';
import type { LoginInput, SessionResponse } from '../types/api';

export const authApi = {
  login: (input: LoginInput) => api<SessionResponse>('/auth/login', { method: 'POST', body: JSON.stringify(input) }),
  me: () => api<SessionResponse>('/auth/me'),
  logout: () => api<void>('/auth/logout', { method: 'POST' }),
};
