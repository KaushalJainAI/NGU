import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { userAPI, publicFetch, API_BASE_URL } from "@/lib/api";
import { isEmailNotVerified } from "@/lib/api/auth";

interface User {
  id: string;
  username: string;
  email: string;
  name?: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
}

interface AuthContextType {
  user: User | null;
  isLoggedIn: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  signup: (userData: any) => Promise<boolean>;
  googleLogin: (accessToken: string) => Promise<boolean>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};

const USER_CACHE_KEY = "user";

/**
 * Synchronously read the cached user so the UI can hydrate to the correct
 * logged-in state on first paint (no logged-out flash). The real auth gate is
 * still the HttpOnly cookie session — this cache is only a display hint and is
 * revalidated against the server on mount.
 */
const readCachedUser = (): User | null => {
  try {
    const raw = localStorage.getItem(USER_CACHE_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
};

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { t } = useTranslation();
  // Hydrate from cache up-front. `user` and thus `isLoggedIn` are correct on the
  // very first render for returning users, eliminating the logged-out flash.
  const [user, setUser] = useState<User | null>(readCachedUser);
  // Only "loading" (i.e. revalidating) when we actually have a session to check.
  const [isLoading, setIsLoading] = useState<boolean>(() => readCachedUser() !== null);

  // Single source of truth for writing/clearing the login-status cache. Writing
  // to localStorage also notifies OTHER tabs via the `storage` event.
  const applyUser = (u: User | null) => {
    setUser(u);
    try {
      if (u) localStorage.setItem(USER_CACHE_KEY, JSON.stringify(u));
      else localStorage.removeItem(USER_CACHE_KEY);
    } catch {
      /* storage unavailable (private mode / quota) — in-memory state still holds */
    }
  };

  // Revalidate the cached session against the server on mount, and keep login
  // status in sync across tabs.
  useEffect(() => {
    let cancelled = false;

    const initAuth = async () => {
      // No cached session → treat as anonymous. Skip the profile probe entirely
      // so guests don't trigger a wasteful getProfile→refresh→401 round-trip on
      // every page load. (If cookies exist but the cache was cleared, the next
      // authenticated action will 401 and prompt a fresh login — an acceptable
      // edge case.)
      if (readCachedUser() === null) {
        setIsLoading(false);
        return;
      }

      try {
        const userData = await userAPI.getProfile();
        if (!cancelled) applyUser(userData);
      } catch (error: any) {
        const status = error?.status || error?.response?.status;
        // 401 is the only definitive "logged out" signal. Everything else
        // (network offline, 5xx, CORS) is transient — keep the cached user so a
        // flaky connection doesn't spuriously log the user out. Authenticated
        // requests remain gated by the cookie regardless of this display state.
        if (status === 401 && !cancelled) applyUser(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    initAuth();

    // authFetch dispatches this when a token refresh definitively fails.
    const handleUnauthorized = () => applyUser(null);

    // Cross-tab sync: mirror login/logout that happened in another tab.
    const handleStorage = (e: StorageEvent) => {
      if (e.key !== USER_CACHE_KEY) return;
      setUser(e.newValue ? (JSON.parse(e.newValue) as User) : null);
    };

    window.addEventListener("auth:unauthorized", handleUnauthorized);
    window.addEventListener("storage", handleStorage);

    return () => {
      cancelled = true;
      window.removeEventListener("auth:unauthorized", handleUnauthorized);
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  const login = async (email: string, password: string): Promise<boolean> => {
    try {
      // A non-2xx response throws APIError, so reaching here means the login
      // succeeded and the HttpOnly cookies are set. We don't depend on the
      // response body carrying `access` — the cookie is the source of truth.
      await userAPI.login(email, password);

      try {
        const userData = await userAPI.getProfile();
        applyUser(userData);
      } catch (profileError) {
        console.error("Failed to fetch profile:", profileError);
        // Login succeeded even if the follow-up profile fetch hiccuped; the
        // mount-time revalidation will populate the user on next load.
      }
      toast.success(t('auth.loginSuccess'));
      return true;
    } catch (error: any) {
      // Right password, unconfirmed email: not a failure to report here — the
      // caller sends the customer to the code screen.
      if (isEmailNotVerified(error)) throw error;
      console.error("Login error:", error);
      toast.error(t('auth.loginFailed'));
      return false;
    }
  };

  const signup = async (userData: any): Promise<boolean> => {
    try {
      const response = await userAPI.register(userData);
      toast.success(t('auth.registerSuccess'));
      return true;
    } catch (error: any) {
      console.error("Signup error:", error);
      const errorMessage = error.data?.detail || error.data?.message || t('auth.registerFailed');
      toast.error(errorMessage);
      return false;
    }
  };

  const googleLogin = async (accessToken: string): Promise<boolean> => {
    try {
      await userAPI.googleLogin(accessToken);
      const userData = await userAPI.getProfile();
      applyUser(userData);
      toast.success(t('auth.googleSuccess'));
      return true;
    } catch (error: any) {
      console.error("Google login error:", error);
      const errorMessage = error.data?.detail || error.data?.message || t('auth.googleFailed');
      toast.error(errorMessage);
      return false;
    }
  };

  const logout = async () => {
    applyUser(null);
    try {
      // publicFetch attaches the X-CSRFToken header. A bare fetch here 403s
      // (CookieJWTAuthentication enforces CSRF while the access_token cookie is
      // still present), which would leave the HttpOnly cookies uncleared
      // server-side. Best-effort: swallow errors so logout always feels instant.
      await publicFetch(`${API_BASE_URL}/auth/logout/`, { method: "POST" });
    } catch (e) {
      console.error(e);
    }
    toast.success(t('auth.logoutSuccess'));
  };

  const refreshUser = async () => {
    try {
      const userData = await userAPI.getProfile();
      applyUser(userData);
    } catch (error) {
      console.error("Failed to refresh user:", error);
    }
  };

  const isLoggedIn = !!user;

  return (
    <AuthContext.Provider 
      value={{ 
        user, 
        isLoggedIn, 
        isLoading, 
        login, 
        logout, 
        signup, 
        googleLogin,
        refreshUser 
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
