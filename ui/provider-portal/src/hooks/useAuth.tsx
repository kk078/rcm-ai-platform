import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { login as authLogin, logout as authLogout, getStoredUser, storeUser, clearStoredUser, type LoginRequest, type ProviderProfile } from '../lib/auth';
import api from '../lib/api';

interface AuthContextValue {
  isAuthenticated: boolean;
  user: ProviderProfile | null;
  login: (payload: LoginRequest) => Promise<void>;
  logout: () => void;
  updateUser: (patch: Partial<ProviderProfile>) => void;
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
  const [user, setUser] = useState<ProviderProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // On startup, restore stored session and hydrate missing practice_name
  useEffect(() => {
    const stored = getStoredUser();
    if (stored) {
      setUser(stored);
      // If practice_name wasn't included in the stored profile, fetch it now
      if (!stored.practice_name && stored.practice_id) {
        api.get('/portal/my-practice').then(({ data }) => {
          if (data?.practice_name) {
            const updated = { ...stored, practice_name: data.practice_name };
            setUser(updated);
            storeUser(updated);
          }
        }).catch(() => { /* non-fatal */ });
      }
    }
    setLoading(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (payload: LoginRequest) => {
    const response = await authLogin(payload);
    const profile: ProviderProfile = {
      id: response.user.id,
      email: response.user.email,
      full_name: response.user.full_name,
      provider_role: response.user.provider_role,
      practice_id: response.user.practice_id,
      practice_name: response.user.practice_name ?? null,
      must_change_password: response.must_change_password ?? false,
    };
    setUser(profile);
    storeUser(profile);

    // If backend didn't return practice_name, fetch it immediately after login
    if (!profile.practice_name && profile.practice_id) {
      try {
        const { data } = await api.get('/portal/my-practice');
        if (data?.practice_name) {
          const withPractice = { ...profile, practice_name: data.practice_name };
          setUser(withPractice);
          storeUser(withPractice);
        }
      } catch {
        // non-fatal
      }
    }
  };

  const logout = () => {
    setUser(null);
    clearStoredUser();
    authLogout();
  };

  const updateUser = (patch: Partial<ProviderProfile>) => {
    setUser(prev => {
      if (!prev) return prev;
      const updated = { ...prev, ...patch };
      storeUser(updated);
      return updated;
    });
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
