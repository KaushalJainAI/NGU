import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { authAPI } from "@/lib/api/auth";
import { useTranslation, Trans } from "react-i18next";

const Register = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    name: "",
    email: "",
    phone: "",
    username: "",
    password: "",
    confirmPassword: "",
    address: "",
    city: "",
    state: "",
    pincode: "",
    profile_picture: "",
  });
  const [isLoading, setIsLoading] = useState(false);
  const [agreedToPrivacy, setAgreedToPrivacy] = useState(false);

  const handleChange = (e) => {
    setFormData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (formData.password !== formData.confirmPassword) {
      toast.error(t('register.passwordMismatch'));
      return;
    }
    if (formData.password.length < 8) {
      toast.error(t('register.passwordTooShort'));
      return;
    }
    if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(formData.password)) {
      toast.error(t('register.passwordComplexity'));
      return;
    }
    if (!agreedToPrivacy) {
      toast.error(t('register.agreePrivacyError'));
      return;
    }
    setIsLoading(true);
    try {
      await authAPI.register({
        first_name: formData.firstName,
        last_name: formData.lastName,
        name: formData.name,
        email: formData.email,
        username: formData.username,
        password: formData.password,
        password2: formData.confirmPassword,
        phone: formData.phone,
        address: formData.address,
        city: formData.city,
        state: formData.state,
        pincode: formData.pincode,
        profile_picture: formData.profile_picture
      });
      // The account cannot log in until the emailed code is entered.
      toast.success(t('register.checkEmail'));
      navigate("/verify-email", { state: { email: formData.email.trim(), password: formData.password } });
    } catch (error: any) {
      console.error("Registration error:", error);
      toast.error(error.message || t('register.failed'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 px-2 py-4 pb-24 md:pb-4">
      <Card className="w-full max-w-lg md:max-w-xl rounded-3xl shadow-xl">
        <CardHeader className="space-y-1">
          <div className="mx-auto mb-2 h-16 w-16 rounded-full spice-backdrop grid place-items-center shadow-sm">
            <img src="/logo.png" alt="Nidhi" className="h-10 w-10 object-contain" />
          </div>
          <CardTitle className="text-2xl font-bold text-center">{t('register.title')}</CardTitle>
          <CardDescription className="text-center">
            {t('register.description')}
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {/* Full Name field */}
            <div>
              <Label htmlFor="name">{t('register.fullName')}</Label>
              <Input
                id="name"
                name="name"
                placeholder="John Doe"
                value={formData.name}
                onChange={handleChange}
                className="mt-2"
              />
            </div>

            {/* Name Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="firstName">{t('register.firstName')}</Label>
                <Input
                  id="firstName"
                  name="firstName"
                  placeholder="John"
                  value={formData.firstName}
                  onChange={handleChange}
                  required
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="lastName">{t('register.lastName')}</Label>
                <Input
                  id="lastName"
                  name="lastName"
                  placeholder="Doe"
                  value={formData.lastName}
                  onChange={handleChange}
                  required
                  className="mt-2"
                />
              </div>
            </div>

            {/* Username & Email Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="username">{t('register.username')}</Label>
                <Input
                  id="username"
                  name="username"
                  type="text"
                  placeholder="johndoe"
                  value={formData.username}
                  onChange={handleChange}
                  required
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="email">{t('register.email')}</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="name@example.com"
                  value={formData.email}
                  onChange={handleChange}
                  required
                  className="mt-2"
                />
              </div>
            </div>

            {/* Phone */}
            <div>
              <Label htmlFor="phone">{t('register.phone')}</Label>
              <Input
                id="phone"
                name="phone"
                type="tel"
                placeholder="+91 98765 43210"
                value={formData.phone}
                onChange={handleChange}
                required
                className="mt-2"
              />
            </div>

            {/* Address Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="address">{t('register.address')}</Label>
                <Input
                  id="address"
                  name="address"
                  placeholder="123 Park Street"
                  value={formData.address}
                  onChange={handleChange}
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="city">{t('register.city')}</Label>
                <Input
                  id="city"
                  name="city"
                  placeholder="Mumbai"
                  value={formData.city}
                  onChange={handleChange}
                  className="mt-2"
                />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="state">{t('register.state')}</Label>
                <Input
                  id="state"
                  name="state"
                  placeholder="Maharashtra"
                  value={formData.state}
                  onChange={handleChange}
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="pincode">{t('register.pincode')}</Label>
                <Input
                  id="pincode"
                  name="pincode"
                  placeholder="400001"
                  value={formData.pincode}
                  onChange={handleChange}
                  className="mt-2"
                />
              </div>
            </div>


            {/* Passwords Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="password">{t('register.password')}</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  value={formData.password}
                  onChange={handleChange}
                  required
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="confirmPassword">{t('register.confirmPassword')}</Label>
                <Input
                  id="confirmPassword"
                  name="confirmPassword"
                  type="password"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  required
                  className="mt-2"
                />
              </div>
            </div>
          </CardContent>
          <CardFooter className="flex flex-col space-y-4 mt-2">
            <div className="flex items-start gap-2 w-full">
              <input
                id="agreePrivacy"
                type="checkbox"
                checked={agreedToPrivacy}
                onChange={(e) => setAgreedToPrivacy(e.target.checked)}
                className="mt-1"
              />
              <Label htmlFor="agreePrivacy" className="text-sm font-normal text-muted-foreground">
                <Trans i18nKey="register.agreePrivacy" components={{ a: <Link to="/privacy-policy" target="_blank" className="text-primary hover:underline" /> }} />
              </Label>
            </div>
            <Button type="submit" className="w-full h-11 rounded-full font-bold bg-primary transition-all" disabled={isLoading || !agreedToPrivacy}>
              {isLoading ? t('register.creating') : t('register.create')}
            </Button>
            <p className="text-sm text-center text-muted-foreground">
              {t('register.haveAccount')}{" "}
              <Link to="/login" className="text-primary hover:underline">
                {t('register.login')}
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
};

export default Register;
