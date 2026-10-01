import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { GoogleOAuthProvider, GoogleLogin as GoogleButton } from '@react-oauth/google';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useToast } from '@/hooks/use-toast';
import { ShoppingBag } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

const GOOGLE_CLIENT_ID =
  (window as unknown as { APP_CONFIG?: { GOOGLE_CLIENT_ID?: string } }).APP_CONFIG?.GOOGLE_CLIENT_ID ||
  (import.meta.env.VITE_GOOGLE_CLIENT_ID as string) ||
  '';

const Login = () => {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const { login, loginWithGoogle, isAuthenticated } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await login(email, password);
      toast({
        title: t('login.successTitle'),
        description: t('login.successBody'),
      });
    } catch (error) {
      toast({
        title: t('login.failedTitle'),
        description: t('login.failedBody'),
        variant: 'destructive',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSuccess = async (credentialResponse: { credential?: string }) => {
    if (!credentialResponse.credential) return;
    setLoading(true);
    try {
      await loginWithGoogle(credentialResponse.credential);
      toast({
        title: t('login.successTitle'),
        description: t('login.successBody'),
      });
    } catch (error: unknown) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (error instanceof Error ? error.message : '');
      toast({
        title: t('login.failedTitle'),
        description: detail || t('login.failedBody'),
        variant: 'destructive',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-gradient-to-br from-primary/5 via-background to-accent/5 p-4">
      {/* The panel shell is behind the login wall, so without this the language
          could not be changed until after signing in — no use to an admin who
          cannot read the sign-in form. */}
      <div className="absolute right-4 top-4">
        <LanguageSwitcher />
      </div>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="space-y-3 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
            <ShoppingBag className="h-7 w-7 text-primary" />
          </div>
          <CardTitle className="text-2xl font-bold">{t('login.title')}</CardTitle>
          <CardDescription>{t('login.subtitle')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">{t('login.email')}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t('login.emailPlaceholder')}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t('login.password')}</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? t('login.submitting') : t('login.submit')}
            </Button>
            {GOOGLE_CLIENT_ID ? (
              <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
                <div className="flex justify-center pt-2">
                  <GoogleButton
                    onSuccess={handleGoogleSuccess}
                    onError={() =>
                      toast({
                        title: t('login.failedTitle'),
                        description: t('login.failedBody'),
                        variant: 'destructive',
                      })
                    }
                    useOneTap={false}
                    theme="outline"
                    shape="rectangular"
                    width="320"
                  />
                </div>
              </GoogleOAuthProvider>
            ) : null}
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default Login;
