import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { GoogleOAuthProvider, GoogleLogin as GoogleButton } from '@react-oauth/google';
import { useAuth } from '@/contexts/AuthContext';
import { confirmEmailVerification, requestEmailVerification } from '@/api/admin';
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
  // Set once the backend says the password is right but the email is
  // unconfirmed: the form then asks for the emailed code instead.
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState('');
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
      if (needsCode) {
        await confirmEmailVerification(email, code, password);
        setNeedsCode(false);
        setCode('');
      }
      await login(email, password);
      toast({
        title: t('login.successTitle'),
        description: t('login.successBody'),
      });
    } catch (error) {
      const response = (error as { response?: { status?: number; data?: { code?: string; detail?: string } } })
        ?.response;
      if (response?.status === 403 && response.data?.code === 'email_not_verified') {
        // A failed send is not fatal: the code step has a resend button.
        await requestEmailVerification(email).catch(() => undefined);
        setNeedsCode(true);
        toast({ title: t('login.verifyTitle'), description: t('login.verifyBody', { email }) });
      } else {
        toast({
          title: t('login.failedTitle'),
          description: (needsCode && response?.data?.detail) || t('login.failedBody'),
          variant: 'destructive',
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    try {
      await requestEmailVerification(email);
      toast({ title: t('login.verifyTitle'), description: t('login.verifyBody', { email }) });
    } catch {
      toast({ title: t('login.failedTitle'), description: t('login.resendFailed'), variant: 'destructive' });
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
                disabled={needsCode}
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
                disabled={needsCode}
                required
              />
            </div>
            {needsCode ? (
              <div className="space-y-2">
                <Label htmlFor="code">{t('login.code')}</Label>
                <Input
                  id="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  required
                />
                <div className="flex justify-between text-sm">
                  <button type="button" className="text-primary hover:underline" onClick={handleResend}>
                    {t('login.resend')}
                  </button>
                  <button
                    type="button"
                    className="text-muted-foreground hover:underline"
                    onClick={() => { setNeedsCode(false); setCode(''); }}
                  >
                    {t('login.useAnotherAccount')}
                  </button>
                </div>
              </div>
            ) : null}
            <Button type="submit" className="w-full" disabled={loading || (needsCode && code.length !== 6)}>
              {loading ? t('login.submitting') : needsCode ? t('login.verifySubmit') : t('login.submit')}
            </Button>
            {GOOGLE_CLIENT_ID && !needsCode ? (
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
