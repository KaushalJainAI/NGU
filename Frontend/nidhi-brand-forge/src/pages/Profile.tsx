import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import PasswordStrength from "@/components/PasswordStrength";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { CreditCard, Trash2, Star, Wallet, MapPin, Loader2 } from "lucide-react";
import Footer from "@/components/Footer";
import ChangeEmailDialog from "@/components/ChangeEmailDialog";
import { useAuth } from "@/context/AuthContext";
import { paymentMethodsAPI, userAPI, geoAPI } from "@/lib/api";
import { useGeolocation } from "@/hooks/useGeolocation";
import { useTranslation } from "react-i18next";

// --- Types ---
interface PaymentMethod {
  id: number;
  payment_type: 'UPI' | 'CARD' | 'NETBANKING' | 'WALLET';
  is_default: boolean;
  is_active: boolean;
  upi_id?: string;
  card_last_four?: string;
  card_brand?: string;
  card_expiry_month?: number | string;
  card_expiry_year?: number | string;
  bank_name?: string;
  wallet_provider?: string;
  masked_display: string;
  created_at: string;
}

const initialPaymentForm = {
  payment_type: 'UPI' as PaymentMethod["payment_type"],
  upi_id: '',
  card_last_four: '',
  card_brand: '',
  card_expiry_month: '',
  card_expiry_year: '',
  bank_name: '',
  wallet_provider: '',
  is_default: false,
};

const Profile = () => {
  const { t } = useTranslation();
  // Profile info and states
  const [profile, setProfile] = useState({
    username: "",
    name: "",
    email: "",
    phone: "",
    address: "",
    city: "",
    state: "",
    pincode: "",
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialLoading, setIsInitialLoading] = useState(true);

  // Location detection for the address fields.
  const geo = useGeolocation();
  const [detectingLocation, setDetectingLocation] = useState(false);
  const { logout, refreshUser } = useAuth();
  const navigate = useNavigate();

  // Payment methods
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);
  const [isLoadingPayments, setIsLoadingPayments] = useState(false);

  // Add Payment
  const [openDialog, setOpenDialog] = useState(false);
  const [newPayment, setNewPayment] = useState(initialPaymentForm);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [isAddingPayment, setIsAddingPayment] = useState(false);

  // Change password section
  const [pwdForm, setPwdForm] = useState({
    currentPassword: "",
    newPassword: "",
    confirmNewPassword: "",
  });
  const [pwdError, setPwdError] = useState("");
  const [pwdSuccess, setPwdSuccess] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);

  useEffect(() => {
    const loadInitialData = async () => {
      setIsInitialLoading(true);
      await fetchProfile();
      setIsInitialLoading(false);
    };
    loadInitialData();
  }, []);

  // Fetch Profile
  const fetchProfile = async () => {
    try {
      const data = await userAPI.getProfile();
      setProfile({
        username: data.username || "",
        name: data.name || "",
        email: data.email || "",
        phone: data.phone || "",
        address: data.address || "",
        city: data.city || "",
        state: data.state || "",
        pincode: data.pincode || "",
      });
    } catch {
      toast.error(t('profile.loadFailed'));
    }
  };

  // Fetch Payment Methods (handles DRF pagination)
  const fetchPaymentMethods = async () => {
    setIsLoadingPayments(true);
    try {
      const data = await paymentMethodsAPI.getAll();
      if (Array.isArray(data.results)) {
        setPaymentMethods(data.results);
      } else if (Array.isArray(data)) {
        setPaymentMethods(data);
      } else {
        setPaymentMethods([]);
      }
    } catch {
      setPaymentMethods([]);
      toast.error(t('profile.paymentsLoadFailed'));
    } finally {
      setIsLoadingPayments(false);
    }
  };

  // Update Profile
  const handleUpdateProfile = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      await userAPI.updateProfile(profile);
      toast.success(t('profile.updateSuccess'));
    } catch {
      toast.error(t('profile.updateFailed'));
    } finally {
      setIsLoading(false);
    }
  };

  // Detect location and fill the address fields. The user still has to press
  // "Save" to make it their default address.
  const handleDetectLocation = async () => {
    setDetectingLocation(true);
    try {
      const coords = await geo.request();
      if (!coords) {
        toast.error(geo.error || t('profile.locationDenied'));
        return;
      }
      const addr = await geoAPI.reverseGeocode(coords.lat, coords.lng);
      setProfile((prev) => ({
        ...prev,
        address: addr.address_line || prev.address,
        city: addr.city || prev.city,
        state: addr.state || prev.state,
        pincode: addr.pincode || prev.pincode,
      }));
      // Store a coarse copy for recommendations (best-effort).
      geoAPI
        .update({
          lat: coords.lat,
          lng: coords.lng,
          city: addr.city,
          state: addr.state,
          pincode: addr.pincode,
        })
        .catch(() => {});
      toast.success(t('profile.addressFilled'));
    } catch {
      toast.error(t('profile.addressFailed'));
    } finally {
      setDetectingLocation(false);
    }
  };

  // Handle Change Password (using POST /change-password/)
  const handleChangePassword = async (e) => {
    e.preventDefault();
    setPwdError("");
    setPwdSuccess("");
    if (!pwdForm.currentPassword || !pwdForm.newPassword || !pwdForm.confirmNewPassword) {
      setPwdError(t('profile.allFieldsRequired'));
      return;
    }
    if (pwdForm.newPassword !== pwdForm.confirmNewPassword) {
      setPwdError(t('profile.passwordMismatch'));
      return;
    }
    setIsChangingPassword(true);
    try {
      await userAPI.changePassword(pwdForm.currentPassword, pwdForm.newPassword);
      setPwdSuccess(t('profile.passwordChanged'));
      setPwdForm({ currentPassword: "", newPassword: "", confirmNewPassword: "" });
    } catch (err) {
      setPwdError(err?.message || t('profile.passwordChangeFailed'));
    } finally {
      setIsChangingPassword(false);
    }
  };

  // ------- FIX IS HERE -------
  const validatePaymentForm = () => {
    const errs: Record<string, string> = {};
    if (newPayment.payment_type === "UPI") {
      if (!newPayment.upi_id.trim()) errs.upi_id = t('profile.errUpiRequired');
    } else if (newPayment.payment_type === "CARD") {
      if (!newPayment.card_brand.trim()) errs.card_brand = t('profile.errCardBrand');
      if (!newPayment.card_last_four.trim() || newPayment.card_last_four.length !== 4) errs.card_last_four = t('profile.errLastFour');
      if (!newPayment.card_expiry_month.trim() || isNaN(Number(newPayment.card_expiry_month)) || Number(newPayment.card_expiry_month) < 1 || Number(newPayment.card_expiry_month) > 12) errs.card_expiry_month = t('profile.errMonth');
      if (!newPayment.card_expiry_year.trim() || newPayment.card_expiry_year.length !== 4) errs.card_expiry_year = t('profile.errYear');
    } else if (newPayment.payment_type === "NETBANKING") {
      if (!newPayment.bank_name.trim()) errs.bank_name = t('profile.errBankName');
    } else if (newPayment.payment_type === "WALLET") {
      if (!newPayment.wallet_provider.trim()) errs.wallet_provider = t('profile.errWalletProvider');
    }
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleAddPaymentMethod = async (e) => {
    e.preventDefault();
    if (!validatePaymentForm()) {
      toast.error(t('profile.fillAllFields'));
      return;
    }
    setIsAddingPayment(true);
    try {
      let paymentData: any = {
        payment_type: newPayment.payment_type,
        is_default: newPayment.is_default,
      };
      if (newPayment.payment_type === "UPI") {
        paymentData.upi_id = newPayment.upi_id;
      } else if (newPayment.payment_type === "CARD") {
        paymentData.card_last_four = newPayment.card_last_four;
        paymentData.card_brand = newPayment.card_brand;
        paymentData.card_expiry_month = Number(newPayment.card_expiry_month);
        paymentData.card_expiry_year = Number(newPayment.card_expiry_year);
        paymentData.gateway_token = `tok_${Date.now()}`;
        paymentData.gateway_name = "razorpay";
      } else if (newPayment.payment_type === "NETBANKING") {
        paymentData.bank_name = newPayment.bank_name;
      } else if (newPayment.payment_type === "WALLET") {
        paymentData.wallet_provider = newPayment.wallet_provider;
      }
      await paymentMethodsAPI.create(paymentData);
      toast.success(t('profile.paymentAdded'));
      setOpenDialog(false);
      await fetchPaymentMethods();
      setNewPayment(initialPaymentForm);
    } catch (err) {
      toast.error(err?.data?.detail || err?.message || t('profile.paymentAddFailed'));
    } finally {
      setIsAddingPayment(false);
      setFormErrors({});
    }
  };
  // --------------------------

  // Remove Payment
  const handleRemovePaymentMethod = async (id) => {
    try {
      await paymentMethodsAPI.delete(id);
      toast.success(t('profile.paymentRemoved'));
      await fetchPaymentMethods();
    } catch {
      toast.error(t('profile.paymentRemoveFailed'));
    }
  };

  // Set default payment method
  const handleSetDefault = async (id) => {
    try {
      await paymentMethodsAPI.setDefault(id);
      toast.success(t('profile.defaultUpdated'));
      await fetchPaymentMethods();
    } catch {
      toast.error(t('profile.defaultFailed'));
    }
  };

  // Payment icon helper
  const getPaymentIcon = (type) => {
    switch (type) {
      case "CARD":
        return <CreditCard className="h-5 w-5" />;
      case "WALLET":
        return <Wallet className="h-5 w-5" />;
      default:
        return <CreditCard className="h-5 w-5" />;
    }
  };

  // Logout with redirect
  const handleLogout = () => {
    logout();
    navigate("/");
  };

  // --- Render ---
  // Show loading spinner while initial data is being fetched
  if (isInitialLoading) {
    return (
      <>
        <div className="container py-4 sm:py-8 px-3 sm:px-4 pb-24 md:pb-8 min-h-[60vh] flex items-center justify-center">
          <div className="flex flex-col items-center gap-4">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            <p className="text-muted-foreground text-sm">{t('profile.loading')}</p>
          </div>
        </div>
        <Footer />
      </>
    );
  }

  return (
    <>
      <div className="container py-4 sm:py-8 px-3 sm:px-4 pb-24 md:pb-8">
        <Tabs defaultValue="profile" className="max-w-3xl mx-auto">
          <TabsList className="grid w-full grid-cols-2 h-9 sm:h-10">
            <TabsTrigger value="profile" className="text-xs sm:text-sm">{t('profile.tabProfile')}</TabsTrigger>
            <TabsTrigger value="security" className="text-xs sm:text-sm">{t('profile.tabSecurity')}</TabsTrigger>
          </TabsList>
          {/* --- Profile Section --- */}
          <TabsContent value="profile">
            <Card>
              <CardHeader className="p-4 sm:p-6">
                <CardTitle className="text-base sm:text-lg">{t('profile.infoTitle')}</CardTitle>
                <CardDescription className="text-xs sm:text-sm">{t('profile.infoDesc')}</CardDescription>
              </CardHeader>
              <CardContent className="p-4 sm:p-6 pt-0 sm:pt-0">
                <form onSubmit={handleUpdateProfile} className="space-y-3 sm:space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="username">{t('profile.username')}</Label>
                    <Input id="username" value={profile.username} onChange={e => setProfile({ ...profile, username: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="name">{t('profile.fullName')}</Label>
                    <Input id="name" value={profile.name || ""} onChange={e => setProfile({ ...profile, name: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="email">{t('profile.email')}</Label>
                    {/* The login email changes only through the code-confirmed dialog. */}
                    <div className="flex gap-2">
                      <Input id="email" type="email" value={profile.email} readOnly className="bg-muted" />
                      <Button type="button" variant="outline" onClick={() => setEmailDialogOpen(true)}>
                        {t('changeEmail.change')}
                      </Button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="phone">{t('profile.phone')}</Label>
                    <Input id="phone" value={profile.phone || ""} onChange={e => setProfile({ ...profile, phone: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <Label htmlFor="address">{t('profile.address')}</Label>
                      {geo.supported && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={handleDetectLocation}
                          disabled={detectingLocation}
                          className="h-7 text-xs"
                        >
                          {detectingLocation ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <MapPin className="h-3.5 w-3.5" />
                          )}
                          <span className="ml-1.5">{t('profile.useLocation')}</span>
                        </Button>
                      )}
                    </div>
                    <Input id="address" value={profile.address || ""} onChange={e => setProfile({ ...profile, address: e.target.value })} />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
                    <div className="space-y-1 sm:space-y-2">
                      <Label htmlFor="city" className="text-xs sm:text-sm">{t('profile.city')}</Label>
                      <Input id="city" className="h-9 sm:h-10 text-sm" value={profile.city || ""} onChange={e => setProfile({ ...profile, city: e.target.value })} />
                    </div>
                    <div className="space-y-1 sm:space-y-2">
                      <Label htmlFor="state" className="text-xs sm:text-sm">{t('profile.state')}</Label>
                      <Input id="state" className="h-9 sm:h-10 text-sm" value={profile.state || ""} onChange={e => setProfile({ ...profile, state: e.target.value })} />
                    </div>
                    <div className="space-y-1 sm:space-y-2">
                      <Label htmlFor="pincode" className="text-xs sm:text-sm">{t('profile.pincode')}</Label>
                      <Input id="pincode" className="h-9 sm:h-10 text-sm" value={profile.pincode || ""} onChange={e => setProfile({ ...profile, pincode: e.target.value })} />
                    </div>
                  </div>
                  <div className="flex gap-3 sm:gap-4">
                    <Button type="submit" disabled={isLoading} className="w-1/2 h-10 sm:h-12 text-sm">
                      {isLoading ? t('profile.updating') : t('profile.updateButton')}
                    </Button>
                    <Button variant="destructive" type="button" onClick={handleLogout} className="w-1/2 h-10 sm:h-12 text-sm">
                      {t('profile.logout')}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </TabsContent>
          {/* --- Security Section (Change password) --- */}
          <TabsContent value="security">
            <Card>
              <CardHeader>
                <CardTitle>{t('profile.securityTitle')}</CardTitle>
                <CardDescription>{t('profile.securityDesc')}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <form onSubmit={handleChangePassword} className="space-y-2">
                  <div className="space-y-2">
                    <Label htmlFor="currentPassword">{t('profile.currentPassword')}</Label>
                    <Input id="currentPassword" type="password" value={pwdForm.currentPassword} onChange={e => setPwdForm({ ...pwdForm, currentPassword: e.target.value })} autoComplete="current-password" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="newPassword">{t('profile.newPassword')}</Label>
                    <Input id="newPassword" type="password" value={pwdForm.newPassword} onChange={e => setPwdForm({ ...pwdForm, newPassword: e.target.value })} autoComplete="new-password" />
                    <PasswordStrength password={pwdForm.newPassword} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="confirmNewPassword">{t('profile.confirmNewPassword')}</Label>
                    <Input id="confirmNewPassword" type="password" value={pwdForm.confirmNewPassword} onChange={e => setPwdForm({ ...pwdForm, confirmNewPassword: e.target.value })} autoComplete="new-password" />
                  </div>
                  <Button type="submit" disabled={isChangingPassword}>
                    {isChangingPassword ? t('profile.changing') : t('profile.changePassword')}
                  </Button>
                  {pwdError && <div className="text-xs text-red-500 mt-2">{pwdError}</div>}
                  {pwdSuccess && <div className="text-xs text-green-500 mt-2">{pwdSuccess}</div>}
                </form>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
      <ChangeEmailDialog
        open={emailDialogOpen}
        onOpenChange={setEmailDialogOpen}
        currentEmail={profile.email}
        onChanged={(email) => {
          setProfile((prev) => ({ ...prev, email }));
          refreshUser();
        }}
      />
      <Footer />
    </>
  );
};

export default Profile;
