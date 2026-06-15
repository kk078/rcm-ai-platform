import api from './api';

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  must_change_password: boolean;
  user: {
    id: string;
    email: string;
    full_name: string;
    provider_role: string;
    practice_id: string;
    practice_name: string;
  };
}

export interface ProviderProfile {
  id: string;
  email: string;
  full_name: string;
  provider_role: string;
  practice_id: string;
  practice_name: string;
  must_change_password?: boolean;
  first_name?: string;
  last_name?: string;
  mfa_enabled?: boolean;
}

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>('/auth/login', payload);
  localStorage.setItem('provider_access_token', data.access_token);
  localStorage.setItem('provider_refresh_token', data.refresh_token);
  return data;
}

export async function refreshToken(): Promise<string> {
  const refresh = localStorage.getItem('provider_refresh_token');
  if (!refresh) throw new Error('No refresh token');
  const { data } = await api.post('/auth/refresh', { refresh_token: refresh });
  localStorage.setItem('provider_access_token', data.access_token);
  localStorage.setItem('provider_refresh_token', data.refresh_token);
  return data.access_token;
}

export function logout(): void {
  localStorage.removeItem('provider_access_token');
  localStorage.removeItem('provider_refresh_token');
  window.location.href = '/portal/login';
}

export function getStoredUser(): ProviderProfile | null {
  const raw = localStorage.getItem('provider_user');
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function storeUser(user: ProviderProfile): void {
  localStorage.setItem('provider_user', JSON.stringify(user));
}

export function clearStoredUser(): void {
  localStorage.removeItem('provider_user');
}
