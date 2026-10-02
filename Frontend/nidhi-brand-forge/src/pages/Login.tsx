import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { authAPI, isEmailNotVerified } from "@/lib/api/auth";
import { GoogleLogin } from "@react-oauth/google";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Link } from "react-router-dom";

const Login: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { login, googleLogin } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const success = await login(email, password);
      // On failure `login` has already shown the reason.
      if (success) navigate("/");
    } catch (error) {
      if (isEmailNotVerified(error)) {
        // The password was right; the inbox is unproven. Mail a code and move
        // to the code screen. A failed send is not fatal — that screen has a
        // resend button.
        await authAPI.resendVerification(email).catch(() => {});
        toast.info(t('auth.verifyFirst'));
        navigate("/verify-email", { state: { email, password } });
        return;
      }
      toast.error(t('auth.networkError'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleSuccess = async (response: any) => {
    setIsLoading(true);
    try {
      const success = await googleLogin(response.credential);
      if (success) {
        navigate("/");
      }
    } catch (error) {
       toast.error(t('auth.googleFailed'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-md mx-auto">
          <Card className="border-border shadow-xl rounded-3xl">
            <CardHeader className="space-y-1">
              <div className="mx-auto mb-2 h-16 w-16 rounded-full spice-backdrop grid place-items-center shadow-sm">
                <img src="/logo.png" alt="Nidhi" className="h-10 w-10 object-contain" />
              </div>
              <CardTitle className="text-2xl font-bold text-center">{t('auth.welcomeBack')}</CardTitle>
              <CardDescription className="text-center">
                {t('auth.subtitle')}
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleSubmit}>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">{t('auth.email')}</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="name@example.com"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    required
                    className="border-border"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">{t('auth.password')}</Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                    className="border-border"
                  />
                </div>
                
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t border-border" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-background px-2 text-muted-foreground">{t('auth.orContinueWith')}</span>
                  </div>
                </div>

                <div className="flex justify-center w-full">
                  <GoogleLogin
                    onSuccess={handleGoogleSuccess}
                    onError={() => toast.error(t('auth.googleFailed'))}
                    useOneTap
                    theme="outline"
                    shape="rectangular"
                    width="360"
                  />
                </div>
              </CardContent>
              <CardFooter className="flex flex-col space-y-4">
                <Button
                  type="submit"
                  className="w-full h-11 rounded-full font-bold bg-primary transition-all"
                  disabled={isLoading}
                >
                  {isLoading ? t('auth.loggingIn') : t('auth.login')}
                </Button>
                <div className="flex flex-col space-y-2 text-center text-sm w-full">
                  <Link to="/forgot-password" className="text-primary hover:underline font-medium">
                    {t('auth.forgotPassword')}
                  </Link>
                  <p className="text-muted-foreground w-full">
                    {t('auth.noAccount')}{" "}
                    <Link to="/register" className="text-primary hover:underline font-medium">
                      {t('auth.registerHere')}
                    </Link>
                  </p>
                </div>
              </CardFooter>
            </form>
          </Card>
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default Login;
