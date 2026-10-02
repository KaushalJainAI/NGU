import React, { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { authAPI } from "@/lib/api/auth";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

/** Seconds before "Resend code" can be pressed again. */
const RESEND_COOLDOWN = 30;

interface VerifyState {
  email?: string;
  password?: string;
}

/**
 * Confirms the 6-digit code emailed at sign-up, then logs the customer in.
 *
 * Reached from Register (code already sent) or from Login when the backend
 * answers `email_not_verified` (Login requests a fresh code first). Both hand
 * over the email AND password in router state: the backend needs the password
 * with the code, and it is what lets us log in straight afterwards. The state
 * lives in memory only, so opening this URL directly sends you to /login.
 */
const VerifyEmail: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { login } = useAuth();
  const { email, password } = (useLocation().state as VerifyState | null) ?? {};

  const [code, setCode] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  if (!email || !password) return <Navigate to="/login" replace />;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (code.length !== 6) {
      toast.error(t("verifyEmail.enterCode"));
      return;
    }
    setIsVerifying(true);
    try {
      await authAPI.verifyEmail(email, code, password);
    } catch (error: any) {
      toast.error(error?.message || t("verifyEmail.failed"));
      setIsVerifying(false);
      return;
    }
    // Verified. A failed login here is a hiccup, not a wrong code — the login
    // page works now, so send them there rather than leaving them stuck.
    const loggedIn = await login(email, password);
    setIsVerifying(false);
    navigate(loggedIn ? "/" : "/login", { replace: true });
  };

  const handleResend = async () => {
    setIsResending(true);
    try {
      await authAPI.resendVerification(email);
      toast.success(t("verifyEmail.resent"));
      setCooldown(RESEND_COOLDOWN);
    } catch (error: any) {
      toast.error(error?.message || t("verifyEmail.resendFailed"));
    } finally {
      setIsResending(false);
    }
  };

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-md mx-auto">
          <Card className="border-border shadow-xl rounded-3xl">
            <CardHeader className="space-y-1">
              <CardTitle className="text-2xl font-bold text-center">{t("verifyEmail.title")}</CardTitle>
              <CardDescription className="text-center">
                {t("verifyEmail.description", { email })}
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleSubmit}>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="otp">{t("verifyEmail.code")}</Label>
                  <Input
                    id="otp"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoFocus
                    maxLength={6}
                    placeholder="123456"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    required
                    className="border-border text-center text-lg tracking-[0.5em]"
                  />
                  <p className="text-xs text-muted-foreground">{t("verifyEmail.hint")}</p>
                </div>
              </CardContent>
              <CardFooter className="flex flex-col space-y-4">
                <Button type="submit" className="w-full h-11 rounded-full font-bold" disabled={isVerifying}>
                  {isVerifying ? t("verifyEmail.verifying") : t("verifyEmail.verify")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="w-full"
                  onClick={handleResend}
                  disabled={isResending || cooldown > 0}
                >
                  {cooldown > 0 ? t("verifyEmail.resendIn", { seconds: cooldown }) : t("verifyEmail.resend")}
                </Button>
                <p className="text-sm text-center text-muted-foreground">
                  {t("verifyEmail.wrongEmail")}{" "}
                  <Link to="/register" className="text-primary hover:underline font-medium">
                    {t("verifyEmail.registerAgain")}
                  </Link>
                </p>
              </CardFooter>
            </form>
          </Card>
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default VerifyEmail;
