import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import {
  login as authLogin, logout as authLogout,
  getStoredUser, storeUser, clearStoredUser,
  type LoginRequest, type UserProfile,
} from '../lib/auth';

interface AuthContextValue {
  isAuthenticated: boolean;
  user: UserProfile | null;
  login: (payload: LoginRequest) => Promise<void>;
  logout: () => void;
  updateUser: (patch: Partial<UserProfile>) => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  user: null,
  login: async () => {},
  logout: () => {},
  updateUser: () => {},
  loading: true,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = getStoredUser();
    if (stored) setUser(stored);
    setLoading(false);
  }, []);

  const login = async (payload: LoginRequest) => {
    const response = await authLogin(payload);
    const userProfile: UserProfile = {
      id: response.user.id,
      email: response.user.email,
      full_name: response.user.full_name,
      first_name: response.user.first_name,
      last_name: response.user.last_name,
      internal_role: response.user.internal_role,
      mfa_enabled: response.user.mfa_enabled,
      assigned_practices: response.user.assigned_practices,
      must_change_password: response.must_change_password ?? false,
    };
    setUser(userProfile);
    storeUser(userProfile);
  };

  const updateUser = (patch: Partial<UserProfile>) => {
    setUser(prev => {
      if (!prev) return prev;
      const updated = { ...prev, ...patch };
      storeUser(updated);
      return updated;
    });
  };

  const logout = () => {
    setUser(null);
    clearStoredUser();
    authLogout();
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!user, user, login, logout, updateUser, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
