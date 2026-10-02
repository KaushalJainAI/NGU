import React, { useState, useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { toast } from "sonner";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { API_BASE_URL } from "@/lib/api";
import { useTranslation } from "react-i18next";

const ResetPassword = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const emailFromState = location.state?.email || "";

  const [email, setEmail] = useState(emailFromState);
  const [otpCode, setOtpCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [resetToken, setResetToken] = useState("");
  const [step, setStep] = useState<"verify" | "reset">("verify");

  useEffect(() => {
    if (!emailFromState) {
        // If they navigate here directly without an email, they should probably go back to forgot-password
        // But we allow manual entry just in case.
    }
  }, [emailFromState]);


  const handleVerifyOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !otpCode || otpCode.length !== 6) {
      toast.error(t('resetPassword.invalidOtp'));
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/auth/password-reset-verify/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, otp_code: otpCode }),
      });

      const data = await response.json();

      if (response.ok) {
        toast.success(t('resetPassword.otpVerified'));
        if (data.reset_token) {
            setResetToken(data.reset_token);
        }
        setStep("reset");
      } else {
        toast.error(data.detail || t('resetPassword.otpExpired'));
      }
    } catch (error) {
      toast.error(t('resetPassword.networkError'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      toast.error(t('resetPassword.passwordMismatch'));
      return;
    }
    if (newPassword.length < 8) {
      toast.error(t('resetPassword.passwordTooShort'));
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/auth/password-reset-confirm/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
            email, 
            reset_token: resetToken, 
            new_password: newPassword, 
            confirm_password: confirmPassword 
        }),
      });

      const data = await response.json();

      if (response.ok) {
        toast.success(t('resetPassword.resetSuccess'));
        navigate("/login");
      } else {
        // Django validation errors can be a string or an array of strings
        if (Array.isArray(data.detail)) {
            data.detail.forEach((err: string) => toast.error(err));
        } else {
            toast.error(data.detail || t('resetPassword.resetFailed'));
        }
      }
    } catch (error) {
      toast.error(t('resetPassword.networkError'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background pb-20 md:pb-0">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-md mx-auto">
          <Card className="border-border shadow-lg mt-8">
            <CardHeader className="space-y-1">
              <CardTitle className="text-2xl font-bold text-center">
                {step === "verify" ? t('resetPassword.verifyTitle') : t('resetPassword.createTitle')}
              </CardTitle>
              <CardDescription className="text-center">
                {step === "verify"
                    ? t('resetPassword.verifyDesc')
                    : t('resetPassword.createDesc')}
              </CardDescription>
            </CardHeader>
            
            {step === "verify" ? (
                <form onSubmit={handleVerifyOTP}>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="email">{t('resetPassword.email')}</Label>
                      <Input
                        id="email"
                        type="email"
                        value={email}
                        onChange={e => setEmail(e.target.value)}
                        required
                        disabled={!!emailFromState} 
                        className="border-border"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="otp">{t('resetPassword.otpLabel')}</Label>
                      <Input
                        id="otp"
                        type="text"
                        maxLength={6}
                        placeholder="123456"
                        value={otpCode}
                        onChange={e => setOtpCode(e.target.value.replace(/\D/g, ''))} // numbers only
                        required
                        className="border-border tracking-widest text-center text-lg font-mono"
                      />
                    </div>
                  </CardContent>
                  <CardFooter className="flex flex-col space-y-4">
                    <Button
                      type="submit"
                      className="w-full bg-primary hover:opacity-90 transition-opacity"
                      disabled={isLoading || otpCode.length !== 6}
                    >
                      {isLoading ? t('resetPassword.verifying') : t('resetPassword.verifyButton')}
                    </Button>
                    <div className="text-sm text-center text-muted-foreground w-full">
                      {t('resetPassword.notReceived')} <Link to="/forgot-password" className="text-primary hover:underline">{t('resetPassword.requestAgain')}</Link>
                    </div>
                  </CardFooter>
                </form>
            ) : (
                <form onSubmit={handleResetPassword}>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="newPassword">{t('resetPassword.newPassword')}</Label>
                      <Input
                        id="newPassword"
                        type="password"
                        value={newPassword}
                        onChange={e => setNewPassword(e.target.value)}
                        required
                        className="border-border"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="confirmPassword">{t('resetPassword.confirmPassword')}</Label>
                      <Input
                        id="confirmPassword"
                        type="password"
                        value={confirmPassword}
                        onChange={e => setConfirmPassword(e.target.value)}
                        required
                        className="border-border"
                      />
                    </div>
                  </CardContent>
                  <CardFooter>
                    <Button
                      type="submit"
                      className="w-full bg-primary hover:opacity-90 transition-opacity"
                      disabled={isLoading}
                    >
                      {isLoading ? t('resetPassword.resetting') : t('resetPassword.resetButton')}
                    </Button>
                  </CardFooter>
                </form>
            )}
          </Card>
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default ResetPassword;
