import axios from 'axios';

// Runtime config injected by the container (config.js) takes precedence,
// then the build-time Vite env var, then the local-dev default.
const runtimeApiUrl = (window as unknown as { APP_CONFIG?: { API_URL?: string } }).APP_CONFIG?.API_URL;

const api = axios.create({
  baseURL: runtimeApiUrl || import.meta.env.VITE_API_URL || 'http://localhost:8000/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Admin-Panel': '1',
  },
});

export const getCookie = (name: string): string | null => {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop()?.split(";").shift() || null;
  return null;
};

// IMPORTANT: Remove Content-Type for FormData to let browser set it with boundary
api.interceptors.request.use((config) => {
  // Let browser set Content-Type with boundary for FormData
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
  }
  
  const csrfToken = getCookie("csrftoken");
  if (csrfToken) {
    config.headers['X-CSRFToken'] = csrfToken;
  }
  
  return config;
});

/**
 * Broadcast when the session is truly gone (refresh failed). AuthContext listens
 * and navigates to /login through the router — we must NEVER assign to
 * window.location here, because that is a full browser reload: the admin loses
 * their filters, dialogs and scroll position, and it looks like the page
 * "refreshed itself" mid-typing.
 */
export const SESSION_EXPIRED_EVENT = 'admin:session-expired';

// The access cookie lives 1 hour; the refresh cookie 7 days. Any request can be
// the unlucky one that lands just after expiry (typically a search keystroke),
// so refresh once and replay it instead of bouncing the admin to /login.
let refreshInFlight: Promise<void> | null = null;

const refreshSession = () => {
  if (!refreshInFlight) {
    // Bare axios, not `api` — a 401 from the refresh call itself must not
    // recurse back into this interceptor.
    refreshInFlight = axios
      .post(`${api.defaults.baseURL}/auth/admin/token/refresh/`, {}, { withCredentials: true, headers: { 'X-Admin-Panel': '1' } })
      .then(() => undefined)
      .finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
};

// Handle auth errors and smartly parse backend form validations
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response) {
      const original = error.config || {};
      const isAuthCall = typeof original.url === 'string' && (
        original.url.includes('/auth/admin/login/') ||
        original.url.includes('/auth/admin/google/') ||
        original.url.includes('/auth/admin/token/refresh/') ||
        original.url.includes('/auth/admin/logout/')
      );
      const onLoginPage = window.location.pathname.includes('/login');

      if (error.response.status === 401 && !original._retried && !isAuthCall && !onLoginPage) {
        original._retried = true;
        try {
          await refreshSession();
          return api(original); // replay the original request transparently
        } catch {
          localStorage.removeItem('admin_token');
          localStorage.removeItem('refresh_token');
          window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
        }
      } else if (error.response.status === 401 && !onLoginPage && !isAuthCall) {
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }

      // Check if there is data on the response and smartly parse it
      const data = error.response.data;
      if (data) {
        if (typeof data === 'string') {
          error.message = data;
        } else if (data.error) {
          error.message = data.error;
        } else if (data.detail) {
          error.message = data.detail;
        } else if (data.non_field_errors && Array.isArray(data.non_field_errors) && data.non_field_errors.length > 0) {
          error.message = data.non_field_errors[0];
        } else if (data.message) {
          error.message = data.message;
        } else if (typeof data === 'object') {
          // Fallback: extract the first validation field exception
          const keys = Object.keys(data);
          if (keys.length > 0) {
            const firstKey = keys[0];
            if (Array.isArray(data[firstKey]) && data[firstKey].length > 0) {
              error.message = `${firstKey.charAt(0).toUpperCase() + firstKey.slice(1).replace(/_/g, ' ')}: ${data[firstKey][0]}`;
            } else if (typeof data[firstKey] === 'string') {
              error.message = data[firstKey];
            }
          }
        }
      }
    }
    
    return Promise.reject(error);
  }
);

export default api;
