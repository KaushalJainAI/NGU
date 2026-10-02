import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getCustomers, getCustomer, Customer, CustomerDetail,
} from '@/api/customers';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { useToast } from '@/hooks/use-toast';
import { Search, ArrowLeft, Phone, Mail, MapPin, MessageCircle, Download, ChevronRight, Loader2, X } from 'lucide-react';
import { exportCustomersCsv } from '@/api/bulk';
import { useIsMobile } from '@/hooks/use-mobile';
import { Skeleton } from '@/components/ui/skeleton';
import { useAdminData } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

const PAGE_SIZE = 12; // matches backend REST_FRAMEWORK PAGE_SIZE

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

/** wa.me link — WhatsApp wants digits only, with country code (assume India). */
const waLink = (phone: string | null) => {
  const digits = (phone || '').replace(/\D/g, '');
  if (!digits) return null;
  const withCc = digits.length === 10 ? `91${digits}` : digits;
  return `https://wa.me/${withCc}`;
};

const Customers = () => {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const isMobile = useIsMobile();

  // What has been typed vs. what has actually been searched for. Typing only
  // moves `searchInput`; nothing reaches the server until Enter or the Search
  // button promotes it to `appliedSearch`.
  const [searchInput, setSearchInput] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [page, setPage] = useState(1);

  // List mode. The key carries the applied query and page, so React Query
  // caches each combination.
  const { data, isInitialLoading, refreshing } = useAdminData(
    ['customers', appliedSearch, page],
    () => getCustomers(appliedSearch, page).then(res => ({
      results: res.data.results || [],
      count: res.data.count || 0,
    })),
    { enabled: !id },
  );

  const submitSearch = () => {
    setPage(1);
    setAppliedSearch(searchInput.trim());
  };

  /** Clearing is instant — asking to see everyone again shouldn't need Enter. */
  const clearSearch = () => {
    setSearchInput('');
    if (appliedSearch) { setPage(1); setAppliedSearch(''); }
  };
  const customers = data?.results ?? [];
  const totalCount = data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  // Detail mode — a separate cache entry per customer, so going back to one
  // already viewed renders immediately.
  const { data: detail, error: detailError, isInitialLoading: detailLoading } =
    useAdminData(['customer', id], () => getCustomer(id!).then(res => res.data), {
      enabled: Boolean(id),
    });

  useEffect(() => {
    if (detailError) navigate('/customers');
  }, [detailError, navigate]);

  if (id && (detailLoading || !detail)) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
        <TableSkeleton rows={5} columns={4} />
      </div>
    );
  }

  // ---------- Detail view ----------
  if (id && detail) {
    const wa = waLink(detail.phone);
    return (
      <div className="space-y-6 p-6">
        <Button variant="ghost" onClick={() => navigate('/customers')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('customers.allCustomers')}
        </Button>

        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{detail.name}</h1>
            <div className="mt-2 space-y-1 text-sm text-muted-foreground">
              <p className="flex items-center gap-2"><Mail className="h-4 w-4" /> {detail.email}</p>
              {detail.phone && (
                <p className="flex items-center gap-2"><Phone className="h-4 w-4" /> {detail.phone}</p>
              )}
              {detail.address && (
                <p className="flex items-center gap-2"><MapPin className="h-4 w-4" /> {detail.address}</p>
              )}
              <p>{t('customers.customerSince', { date: formatDate(detail.created_at) })}</p>
            </div>
          </div>
          {wa && (
            <Button asChild className="bg-green-600 hover:bg-green-700">
              <a href={wa} target="_blank" rel="noreferrer">
                <MessageCircle className="mr-2 h-4 w-4" /> {t('customers.whatsapp')}
              </a>
            </Button>
          )}
        </div>

        <div className="grid gap-4 grid-cols-2">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('customers.ordersPlaced')}</CardTitle></CardHeader>
            <CardContent><div className="text-3xl font-bold">{detail.order_count}</div></CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('customers.totalSpent')}</CardTitle></CardHeader>
            <CardContent><div className="text-3xl font-bold">₹{Number(detail.total_spent).toLocaleString('en-IN')}</div></CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader><CardTitle>{t('customers.orderHistory')}</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            {detail.orders.length === 0 ? (
              <p className="text-center text-muted-foreground py-6">{t('customers.noOrders')}</p>
            ) : (
              <Table className="min-w-[500px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('customers.colOrder')}</TableHead>
                    <TableHead>{t('common.date')}</TableHead>
                    <TableHead>{t('orders.colPayment')}</TableHead>
                    <TableHead>{t('common.status')}</TableHead>
                    <TableHead className="text-right">{t('common.total')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.orders.map(o => (
                    <TableRow
                      key={o.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/orders?search=${o.id}`)}
                    >
                      <TableCell className="font-medium">{o.order_number}</TableCell>
                      <TableCell>{formatDate(o.created_at)}</TableCell>
                      <TableCell>{o.payment_method || '—'}</TableCell>
                      <TableCell>
                        {t(`orderStatus.${o.status}`, { defaultValue: o.status })}
                      </TableCell>
                      <TableCell className="text-right font-mono">₹{o.total_amount}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------- List view ----------
  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('customers.title')}</h1>
          <p className="text-muted-foreground">{t('customers.subtitle')}</p>
        </div>
        <Button variant="outline" onClick={() => exportCustomersCsv()}>
          <Download className="mr-2 h-4 w-4" /> {t('customers.exportButton')}
        </Button>
      </div>

      <PageHelp>{t('customers.pageHelp')}</PageHelp>

      <Card>
        <CardHeader>
          {/* Typing does nothing on its own — Enter or the Search button runs it. */}
          <div className="flex max-w-xl items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('customers.searchPlaceholder')}
                className="pl-8 pr-8"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); submitSearch(); }
                  if (e.key === 'Escape') clearSearch();
                }}
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={clearSearch}
                  title={t('customers.clearSearch')}
                  className="absolute right-2 top-2.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <Button onClick={submitSearch} disabled={refreshing}>
              {refreshing
                ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                : <Search className="mr-2 h-4 w-4" />}
              {t('common.search')}
            </Button>
          </div>
          {appliedSearch !== searchInput.trim() && searchInput.trim() && (
            <p className="text-xs text-muted-foreground pt-1">{t('customers.pressEnter')}</p>
          )}
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing && !isInitialLoading ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? (
            <TableSkeleton rows={6} columns={5} />
          ) : customers.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">
              {appliedSearch ? t('customers.noMatch') : t('customers.empty')}
            </p>
          ) : isMobile ? (
            // Mobile: stacked cards instead of a wide horizontally-scrolling table.
            <div className="space-y-2">
              {customers.map(c => (
                <button
                  key={c.id}
                  onClick={() => navigate(`/customers/${c.id}`)}
                  className="flex w-full items-center justify-between rounded-lg border p-3 text-left"
                >
                  <div className="min-w-0">
                    <p className="font-medium truncate">{c.name}</p>
                    <p className="text-xs text-muted-foreground truncate">{c.phone || c.email}</p>
                    <p className="text-xs text-muted-foreground">
                      {t('customers.ordersCount', { count: c.order_count })}
                      {' · '}₹{Number(c.total_spent).toLocaleString('en-IN')}
                    </p>
                  </div>
                  <ChevronRight className="h-5 w-5 flex-shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>
          ) : (
            <Table className="min-w-[600px]">
              <TableHeader>
                <TableRow>
                  <TableHead>{t('common.name')}</TableHead>
                  <TableHead>{t('customers.colContact')}</TableHead>
                  <TableHead>{t('customers.colLocation')}</TableHead>
                  <TableHead>{t('customers.colOrders')}</TableHead>
                  <TableHead className="text-right">{t('customers.colTotalSpent')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {customers.map(c => (
                  <TableRow
                    key={c.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/customers/${c.id}`)}
                  >
                    <TableCell className="font-medium">{c.name}</TableCell>
                    <TableCell>
                      <div className="text-sm">{c.phone || '—'}</div>
                      <div className="text-xs text-muted-foreground">{c.email}</div>
                    </TableCell>
                    <TableCell>{[c.city, c.state].filter(Boolean).join(', ') || '—'}</TableCell>
                    <TableCell>{c.order_count}</TableCell>
                    <TableCell className="text-right font-mono">
                      ₹{Number(c.total_spent).toLocaleString('en-IN')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4">
              <p className="text-sm text-muted-foreground">
                {t('customers.pager', { page, total: totalPages, count: totalCount })}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                  {t('common.previous')}
                </Button>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                  {t('common.next')}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Customers;
