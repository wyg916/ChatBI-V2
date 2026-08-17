import { createContext, useContext, useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { authApi } from './api/auth';
import type { SessionUser } from './types/api';

type AuthState = { user: SessionUser; logout: () => Promise<void> };
export const AuthContext = createContext<AuthState | null>(null);

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside ProtectedRoute');
  return value;
}

export function ProtectedRoute() {
  const location = useLocation();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    const refresh = () => authApi.me().then((value) => { if (active) setUser(value.user); }).catch(() => { if (active) setUser(null); }).finally(() => { if (active) setLoading(false); });
    refresh();
    const unauthorized = () => { setUser(null); setLoading(false); };
    window.addEventListener('chatbi:unauthorized', unauthorized);
    return () => { active = false; window.removeEventListener('chatbi:unauthorized', unauthorized); };
  }, []);
  if (loading) return <main className="auth-loading">正在验证会话…</main>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  const logout = async () => { await authApi.logout(); setUser(null); };
  return <AuthContext.Provider value={{ user, logout }}><Outlet /></AuthContext.Provider>;
}
