import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { API_BASE_URL } from "@/lib/api";
import { useTranslation } from "react-i18next";

const ForgotPassword = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) {
      toast.error(t('forgotPassword.enterEmail'));
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/auth/password-reset-request/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (response.ok) {
        toast.success(t('forgotPassword.otpSent'));
        // Redirect to ResetPassword page with email in state so user doesn't have to re-type it
        navigate("/reset-password", { state: { email } });
      } else {
        toast.error(data.detail || t('forgotPassword.otpFailed'));
      }
    } catch (error) {
      toast.error(t('forgotPassword.networkError'));
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
              <CardTitle className="text-2xl font-bold text-center">{t('forgotPassword.title')}</CardTitle>
              <CardDescription className="text-center">
                {t('forgotPassword.description')}
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleSubmit}>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">{t('forgotPassword.email')}</Label>
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
              </CardContent>
              <CardFooter className="flex flex-col space-y-4">
                <Button
                  type="submit"
                  className="w-full bg-primary hover:opacity-90 transition-opacity"
                  disabled={isLoading}
                >
                  {isLoading ? t('forgotPassword.sending') : t('forgotPassword.sendOtp')}
                </Button>
                <div className="flex justify-between w-full text-sm text-muted-foreground">
                  <Link to="/login" className="hover:text-primary transition-colors flex items-center gap-1">
                    &larr; {t('forgotPassword.backToLogin')}
                  </Link>
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

export default ForgotPassword;
