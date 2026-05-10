import api from './api';

export interface LoginRequest {
  email: string;
  password: string;
  mfa_code?: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: {
    id: string;
    email: string;
    full_name: string;
    internal_role: string;
    assigned_practices: string[];
  };
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  internal_role: string;
  assigned_practices: string[];
}

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>('/auth/login', payload);
  localStorage.setItem('staff_access_token', data.access_token);
  localStorage.setItem('staff_refresh_token', data.refresh_token);
  return data;
}

export async function refreshToken(): Promise<string> {
  const refresh = localStorage.getItem('staff_refresh_token');
  if (!refresh) throw new Error('No refresh token');
  const { data } = await api.post('/auth/refresh', { refresh_token: refresh });
  localStorage.setItem('staff_access_token', data.access_token);
  localStorage.setItem('staff_refresh_token', data.refresh_token);
  return data.access_token;
}

export function logout(): void {
  localStorage.removeItem('staff_access_token');
  localStorage.removeItem('staff_refresh_token');
  window.location.href = '/login';
}

export function getStoredUser(): UserProfile | null {
  const raw = localStorage.getItem('staff_user');
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function storeUser(user: UserProfile): void {
  localStorage.setItem('staff_user', JSON.stringify(user));
}

export function clearStoredUser(): void {
  localStorage.removeItem('staff_user');
}