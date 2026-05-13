import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor: attach JWT access token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('provider_access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: transform error detail arrays into strings + auto-redirect on 401
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Transform FastAPI validation error arrays into a clean string
    if (error.response?.data?.detail && Array.isArray(error.response.data.detail)) {
      error.response.data.detail = error.response.data.detail
        .map((e: any) => {
          if (typeof e === 'string') return e;
          if (e.msg) {
            const field = e.loc ? e.loc.filter((l: any) => l !== 'body').join(' → ') : '';
            return field ? `${field}: ${e.msg}` : e.msg;
          }
          return JSON.stringify(e);
        })
        .join('. ');
    }

    // Auto-redirect to login on 401 (unless already on login page or refreshing token)
    if (error.response?.status === 401 && !error.config._retry) {
      const originalRequest = error.config;
      originalRequest._retry = true;
      const refreshToken = localStorage.getItem('provider_refresh_token');

      if (refreshToken) {
        try {
          const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
            refresh_token: refreshToken,
          });
          localStorage.setItem('provider_access_token', data.access_token);
          if (data.refresh_token) {
            localStorage.setItem('provider_refresh_token', data.refresh_token);
          }
          originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
          return api(originalRequest);
        } catch {
          localStorage.removeItem('provider_access_token');
          localStorage.removeItem('provider_refresh_token');
          localStorage.removeItem('provider_user');
          if (!window.location.pathname.includes('/login')) {
            window.location.href = '/login';
          }
          return Promise.reject(error);
        }
      } else {
        localStorage.removeItem('provider_access_token');
        localStorage.removeItem('provider_user');
        if (!window.location.pathname.includes('/login')) {
          window.location.href = '/login';
        }
      }
    }

    return Promise.reject(error);
  },
);

export default api;