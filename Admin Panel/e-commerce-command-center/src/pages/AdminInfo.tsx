import { useEffect, useState } from 'react';
import { getAdminInfo, updateAdminInfo, AdminInfo as AdminInfoType } from '@/api/admin';
import { 
  getReceivableAccounts, 
  createReceivableAccount, 
  updateReceivableAccount, 
  ReceivableAccount 
} from '@/api/receivableAccounts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { Save, User, Loader2, CreditCard } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

const AdminInfo = () => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingAccount, setSavingAccount] = useState(false);
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    username: '',
    phone: '',
    address: '',
    city: '',
    state: '',
    pincode: '',
  });
  const [accountData, setAccountData] = useState<ReceivableAccount | null>(null);
  const [accountForm, setAccountForm] = useState({
    account_holder_name: '',
    upi_id: '',
    bank_name: '',
    bank_account_number: '',
    ifsc_code: '',
    branch_name: '',
    contact_email: '',
    contact_phone: '',
  });
  const { toast } = useToast();

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [adminResponse, accountsResponse] = await Promise.all([
        getAdminInfo(),
        getReceivableAccounts()
      ]);

      const adminData = adminResponse.data;
      setFormData({
        first_name: adminData.first_name || '',
        last_name: adminData.last_name || '',
        email: adminData.email || '',
        username: adminData.username || '',
        phone: adminData.phone || '',
        address: adminData.address || '',
        city: adminData.city || '',
        state: adminData.state || '',
        pincode: adminData.pincode || '',
      });

      // Use first receivable account if exists
      if (accountsResponse.data && accountsResponse.data.length > 0) {
        const acc = accountsResponse.data[0];
        setAccountData(acc);
        setAccountForm({
          account_holder_name: acc.account_holder_name || '',
          upi_id: acc.upi_id || '',
          bank_name: acc.bank_name || '',
          bank_account_number: acc.bank_account_number || '',
          ifsc_code: acc.ifsc_code || '',
          branch_name: acc.branch_name || '',
          contact_email: acc.contact_email || '',
          contact_phone: acc.contact_phone || '',
        });
      }
    } catch (error) {
      console.error('Failed to load data:', error);
      toast({
        title: t('common.error'),
        description: t('adminInfo.loadFailed'),
        variant: 'destructive',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updateData: Partial<AdminInfoType> = {
        first_name: formData.first_name,
        last_name: formData.last_name,
        phone: formData.phone,
        address: formData.address,
        city: formData.city,
        state: formData.state,
        pincode: formData.pincode,
      };

      await updateAdminInfo(updateData);
      toast({
        title: t('products.successTitle'),
        description: t('adminInfo.profileSaved'),
      });
    } catch (error) {
      console.error('Failed to update profile:', error);
      toast({
        title: t('common.error'),
        description: t('adminInfo.profileSaveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingAccount(true);
    try {
      if (accountData?.id) {
        await updateReceivableAccount(accountData.id, accountForm);
      } else {
        const newAccount = await createReceivableAccount(accountForm);
        setAccountData(newAccount);
      }
      toast({
        title: t('products.successTitle'),
        description: t('adminInfo.paymentSaved'),
      });
    } catch (error) {
      console.error('Failed to save payment details:', error);
      toast({
        title: t('common.error'),
        description: t('adminInfo.paymentSaveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSavingAccount(false);
    }
  };

  if (loading) {
    // Shaped like the two cards below rather than a centred spinner, so the
    // heading and card outlines don't jump into place when the data lands.
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold">{t('adminInfo.title')}</h1>
        <p className="text-muted-foreground">{t('adminInfo.subtitle')}</p>
      </div>

      <PageHelp>{t('adminInfo.pageHelp')}</PageHelp>

      {/* Profile Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="p-3 bg-primary/10 rounded-full">
              <User className="h-6 w-6 text-primary" />
            </div>
            <div>
              <CardTitle>{t('adminInfo.profileTitle')}</CardTitle>
              <CardDescription>{t('adminInfo.profileDescription')}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSaveProfile} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="first_name">{t('adminInfo.firstName')}</Label>
                <Input
                  id="first_name"
                  value={formData.first_name}
                  onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="last_name">{t('adminInfo.lastName')}</Label>
                <Input
                  id="last_name"
                  value={formData.last_name}
                  onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="email">{t('common.email')}</Label>
                <Input id="email" value={formData.email} disabled className="bg-muted" />
              </div>
              <div>
                <Label htmlFor="phone">{t('common.phone')}</Label>
                <Input
                  id="phone"
                  value={formData.phone}
                  onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                />
              </div>
            </div>

            <div>
              <Label htmlFor="address">{t('adminInfo.address')}</Label>
              <Input
                id="address"
                value={formData.address}
                onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <Label htmlFor="city">{t('adminInfo.city')}</Label>
                <Input
                  id="city"
                  value={formData.city}
                  onChange={(e) => setFormData({ ...formData, city: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="state">{t('adminInfo.state')}</Label>
                <Input
                  id="state"
                  value={formData.state}
                  onChange={(e) => setFormData({ ...formData, state: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="pincode">{t('adminInfo.pincode')}</Label>
                <Input
                  id="pincode"
                  value={formData.pincode}
                  onChange={(e) => setFormData({ ...formData, pincode: e.target.value })}
                />
              </div>
            </div>

            <Button type="submit" disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              {saving ? t('common.saving') : t('adminInfo.saveProfile')}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Payment/Receivable Account Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="p-3 bg-green-500/10 rounded-full">
              <CreditCard className="h-6 w-6 text-green-600" />
            </div>
            <div>
              <CardTitle>{t('adminInfo.paymentTitle')}</CardTitle>
              <CardDescription>{t('adminInfo.paymentDescription')}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSaveAccount} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="account_holder_name">{t('adminInfo.accountHolder')}</Label>
                <Input
                  id="account_holder_name"
                  value={accountForm.account_holder_name}
                  onChange={(e) => setAccountForm({ ...accountForm, account_holder_name: e.target.value })}
                  required
                  placeholder={t('adminInfo.accountHolderPlaceholder')}
                />
              </div>
              <div>
                <Label htmlFor="upi_id">{t('adminInfo.upiId')}</Label>
                <Input
                  id="upi_id"
                  value={accountForm.upi_id}
                  onChange={(e) => setAccountForm({ ...accountForm, upi_id: e.target.value })}
                  required
                  placeholder={t('adminInfo.upiPlaceholder')}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="bank_name">{t('adminInfo.bankName')}</Label>
                <Input
                  id="bank_name"
                  value={accountForm.bank_name}
                  onChange={(e) => setAccountForm({ ...accountForm, bank_name: e.target.value })}
                  placeholder={t('adminInfo.bankNamePlaceholder')}
                />
              </div>
              <div>
                <Label htmlFor="branch_name">{t('adminInfo.branchName')}</Label>
                <Input
                  id="branch_name"
                  value={accountForm.branch_name}
                  onChange={(e) => setAccountForm({ ...accountForm, branch_name: e.target.value })}
                  placeholder={t('adminInfo.branchNamePlaceholder')}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="bank_account_number">{t('adminInfo.accountNumber')}</Label>
                <Input
                  id="bank_account_number"
                  value={accountForm.bank_account_number}
                  onChange={(e) => setAccountForm({ ...accountForm, bank_account_number: e.target.value })}
                  placeholder="1234567890"
                />
              </div>
              <div>
                <Label htmlFor="ifsc_code">{t('adminInfo.ifsc')}</Label>
                <Input
                  id="ifsc_code"
                  value={accountForm.ifsc_code}
                  onChange={(e) => setAccountForm({ ...accountForm, ifsc_code: e.target.value.toUpperCase() })}
                  placeholder="SBIN0001234"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="contact_email">{t('adminInfo.contactEmail')}</Label>
                <Input
                  id="contact_email"
                  type="email"
                  value={accountForm.contact_email}
                  onChange={(e) => setAccountForm({ ...accountForm, contact_email: e.target.value })}
                  placeholder="contact@example.com"
                />
              </div>
              <div>
                <Label htmlFor="contact_phone">{t('adminInfo.contactPhone')}</Label>
                <Input
                  id="contact_phone"
                  value={accountForm.contact_phone}
                  onChange={(e) => setAccountForm({ ...accountForm, contact_phone: e.target.value })}
                  placeholder="+91 98765 43210"
                />
              </div>
            </div>

            <Button type="submit" disabled={savingAccount} className="bg-green-600 hover:bg-green-700">
              {savingAccount ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              {savingAccount ? t('common.saving') : t('adminInfo.savePayment')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default AdminInfo;
