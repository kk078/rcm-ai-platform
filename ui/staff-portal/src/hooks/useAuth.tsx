import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { login as authLogin, logout as authLogout, getStoredUser, storeUser, clearStoredUser, type LoginRequest, type UserProfile } from '../lib/auth';

interface AuthContextValue {
  isAuthenticated: boolean;
  user: UserProfile | null;
  login: (payload: LoginRequest) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  user: null,
  login: async () => {},
  logout: () => {},
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
      internal_role: response.user.internal_role,
      assigned_practices: response.user.assigned_practices,
    };
    setUser(userProfile);
    storeUser(userProfile);
  };

  const logout = () => {
    setUser(null);
    clearStoredUser();
    authLogout();
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!user, user, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}