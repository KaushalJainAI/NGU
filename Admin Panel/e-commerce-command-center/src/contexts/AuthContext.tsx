import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { login as apiLogin, googleLogin, getAdminInfo, AdminInfo } from '@/api/admin';
import api, { SESSION_EXPIRED_EVENT } from '@/api/axiosInstance';

interface AuthContextType {
  isAuthenticated: boolean;
  user: AdminInfo | null;
  login: (email: string, password: string) => Promise<void>;
  loginWithGoogle: (credential: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState<AdminInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchUserProfile = async () => {
    try {
      const response = await getAdminInfo();
      setUser(response.data);
    } catch (error) {
      console.error('Failed to fetch user profile:', error);
      // If fetching profile fails, the token might be invalid
      setUser(null);
    }
  };

  useEffect(() => {
    const initAuth = async () => {
      try {
        const response = await getAdminInfo();
        if (response.data.is_staff === true) {
          setUser(response.data);
          setIsAuthenticated(true);
        } else {
          setIsAuthenticated(false);
          setUser(null);
        }
      } catch (error) {
        setIsAuthenticated(false);
        setUser(null);
      }
      setLoading(false);
    };
    initAuth();
  }, []);

  // The axios interceptor fires this once a silent token refresh has failed.
  // Handling it here keeps the exit client-side (router navigation) instead of
  // a full page reload from window.location.
  useEffect(() => {
    const onExpired = () => {
      setIsAuthenticated(false);
      setUser(null);
      navigate('/login', { replace: true, state: { from: window.location.pathname } });
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [navigate]);

  const login = async (email: string, password: string) => {
    try {
      await apiLogin({ email, password });
      const profile = await getAdminInfo();
      if (profile.data.is_staff !== true) {
        setIsAuthenticated(false);
        setUser(null);
        throw new Error('Not an admin account');
      }
      setUser(profile.data);
      setIsAuthenticated(true);
      navigate('/dashboard');
    } catch (error) {
      throw error instanceof Error ? error : new Error('Invalid credentials');
    }
  };

  const loginWithGoogle = async (credential: string) => {
    await googleLogin(credential);
    const profile = await getAdminInfo();
    if (profile.data.is_staff !== true) {
      setIsAuthenticated(false);
      setUser(null);
      throw new Error('Not an admin account');
    }
    setUser(profile.data);
    setIsAuthenticated(true);
    navigate('/dashboard');
  };

  const logout = async () => {
    // Just clear the cookies server-side. (This used to also fire a login call
    // with empty credentials, which burned a slot in the 5/min login throttle
    // on every logout.)
    try {
      await api.post('/auth/admin/logout/');
    } catch (e) { /* logging out locally regardless */ }
    setIsAuthenticated(false);
    setUser(null);
    navigate('/login');
  };

  const refreshUser = async () => {
    if (isAuthenticated) {
      await fetchUserProfile();
    }
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, login, loginWithGoogle, logout, loading, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
};
