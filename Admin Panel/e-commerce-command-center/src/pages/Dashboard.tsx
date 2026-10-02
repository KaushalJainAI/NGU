import { useNavigate } from 'react-router-dom';
import { useAdminData } from '@/hooks/useAdminData';
import { Skeleton } from '@/components/ui/skeleton';
import {
  getDashboardStats, DashboardStats,
  getDashboardActions, DashboardActions,
} from '@/api/dashboard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { KpiCard } from '@/components/insights/KpiCard';
import {
  Package, ShoppingCart, MessagesSquare, AlertTriangle,
  PackageCheck, CheckCircle2, ArrowRight, MailOpen, MessageCircle,
  Banknote, Receipt, Truck,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

/** One "needs your attention" card: plain sentence + a button that jumps
 *  straight to the pre-filtered page where the admin can act. */
interface ActionItem {
  key: string;
  count: number;
  sentence: string;
  buttonLabel: string;
  to: string;
  icon: typeof ShoppingCart;
  urgent?: boolean;
}

/** Mirrors the real dashboard's shape so the layout doesn't jump when data lands. */
const DashboardSkeleton = () => (
  <div className="space-y-6" aria-busy="true">
    <Skeleton className="h-9 w-64" />
    <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
      <Skeleton className="h-28" />
      <Skeleton className="h-28" />
      <Skeleton className="h-28" />
      <Skeleton className="h-28" />
    </div>
    <Skeleton className="h-6 w-48" />
    <div className="space-y-3">
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
    </div>
    <Skeleton className="h-48" />
  </div>
);

const Dashboard = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const { data: stats, isInitialLoading: statsLoading } =
    useAdminData(['dashboard', 'stats'], () => getDashboardStats().then(r => r.data));
  // The action inbox polls itself so a new order shows up without a reload.
  const { data: actions, isInitialLoading: actionsLoading } = useAdminData(
    ['dashboard', 'actions'],
    () => getDashboardActions().then(r => r.data),
    { refetchInterval: 60_000 },
  );

  if (statsLoading || actionsLoading) {
    return <DashboardSkeleton />;
  }

  // Counting is left to i18next's plural rules rather than an "add an s" helper:
  // English and Hindi disagree about when a noun changes shape, so the helper
  // could only ever have been right about one of them.
  const lowStockNames = !actions?.low_stock_items?.length
    ? ''
    : ` — ${actions.low_stock_items.slice(0, 3).map(i => (i.size ? `${i.name} (${i.size})` : i.name)).join(', ')}${
        actions.low_stock_count > 3 ? '…' : ''
      }`;

  const actionItems: ActionItem[] = !actions ? [] : [
    {
      key: 'confirm',
      count: actions.orders_to_confirm,
      sentence: t('dashboard.action.confirm', { count: actions.orders_to_confirm }),
      buttonLabel: t('dashboard.action.confirmButton'),
      to: '/orders?status=pending',
      icon: ShoppingCart,
      urgent: true,
    },
    {
      key: 'ship',
      count: actions.orders_to_ship,
      sentence: t('dashboard.action.ship', { count: actions.orders_to_ship }),
      buttonLabel: t('dashboard.action.viewOrders'),
      to: '/orders?status=confirmed',
      icon: PackageCheck,
    },
    {
      key: 'stock',
      count: actions.low_stock_count,
      sentence: t('dashboard.action.stock', {
        count: actions.low_stock_count,
        names: lowStockNames,
      }),
      buttonLabel: t('dashboard.action.stockButton'),
      to: '/products?stock=low',
      icon: Package,
    },
    {
      key: 'chats',
      count: actions.chats_waiting,
      sentence: t('dashboard.action.chats', { count: actions.chats_waiting }),
      buttonLabel: t('dashboard.action.chatsButton'),
      to: '/conversations',
      icon: MessagesSquare,
      urgent: true,
    },
    {
      key: 'unread-chats',
      count: actions.unread_chats,
      sentence: t('dashboard.action.unreadChats', { count: actions.unread_chats }),
      buttonLabel: t('dashboard.action.unreadChatsButton'),
      to: '/conversations',
      icon: MessageCircle,
      urgent: true,
    },
    {
      key: 'contacts',
      count: actions.new_contacts,
      sentence: t('dashboard.action.contacts', { count: actions.new_contacts }),
      buttonLabel: t('dashboard.action.contactsButton'),
      to: '/contact?status=new',
      icon: MailOpen,
      urgent: true,
    },
    {
      key: 'stuck',
      count: actions.stuck_payments,
      sentence: t('dashboard.action.stuck', { count: actions.stuck_payments }),
      buttonLabel: t('dashboard.action.viewOrders'),
      to: '/orders?status=pending',
      icon: AlertTriangle,
    },
    {
      key: 'unshipped-aged',
      count: actions.orders_unshipped_aged ?? 0,
      sentence: t('dashboard.action.unshippedAged', { count: actions.orders_unshipped_aged ?? 0 }),
      buttonLabel: t('dashboard.action.viewOrders'),
      to: '/orders?status=confirmed',
      icon: Truck,
      urgent: true,
    },
    {
      key: 'out-of-stock',
      count: actions.out_of_stock_count ?? 0,
      sentence: t('dashboard.action.outOfStock', { count: actions.out_of_stock_count ?? 0 }),
      buttonLabel: t('dashboard.action.stockButton'),
      to: '/products?stock=low',
      icon: Package,
      urgent: true,
    },
    {
      key: 'invoices-missing',
      count: actions.invoices_missing ?? 0,
      sentence: t('dashboard.action.invoicesMissing', { count: actions.invoices_missing ?? 0 }),
      buttonLabel: t('dashboard.action.viewOrders'),
      to: '/orders',
      icon: Receipt,
      urgent: true,
    },
    {
      key: 'unclassified-hsn',
      count: actions.unclassified_hsn_count ?? 0,
      sentence: t('dashboard.action.unclassifiedHsn', { count: actions.unclassified_hsn_count ?? 0 }),
      buttonLabel: t('dashboard.action.openGst'),
      to: '/gst',
      icon: Receipt,
    },
    {
      key: 'failed-payments',
      count: actions.failed_payments_today ?? 0,
      sentence: t('dashboard.action.failedPayments', { count: actions.failed_payments_today ?? 0 }),
      buttonLabel: t('dashboard.action.viewOrders'),
      to: '/orders?status=pending',
      icon: AlertTriangle,
    },
  ].filter(item => item.count > 0);

  const hour = new Date().getHours();
  const greeting =
    hour < 12
      ? t('dashboard.greetingMorning')
      : hour < 17
        ? t('dashboard.greetingAfternoon')
        : t('dashboard.greetingEvening');

  const topSellers = actions?.top_products_7d ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">{greeting}</h1>
        <p className="text-muted-foreground">{t('dashboard.subtitle')}</p>
      </div>

      {/* Four KPI cards: real (paid/booked) sales with period comparisons. */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <div>
          <KpiCard
            title={t('dashboard.salesToday')}
            value={`₹${Number(actions?.today_sales ?? 0).toLocaleString('en-IN')}`}
            delta={actions?.today_sales_delta_pct ?? null}
            hint={t('dashboard.vsLastWeek')}
          />
          <p className="text-xs text-muted-foreground mt-1">
            {t('dashboard.onlineCodSplit', {
              online: Number(actions?.today_online_received ?? 0).toLocaleString('en-IN'),
              cod: Number(actions?.today_cod_booked ?? 0).toLocaleString('en-IN'),
            })}
          </p>
        </div>
        <KpiCard
          title={t('dashboard.ordersToday')}
          value={String(actions?.today_real_orders ?? 0)}
        />
        <KpiCard
          title={t('dashboard.avgOrder')}
          value={`₹${Number(actions?.today_aov ?? 0).toLocaleString('en-IN')}`}
        />
        <KpiCard
          title={t('dashboard.thisMonth')}
          value={`₹${Number(actions?.mtd_sales ?? 0).toLocaleString('en-IN')}`}
          delta={actions?.mtd_sales_delta_pct ?? null}
          hint={t('dashboard.vsPrevMtd')}
        />
      </div>

      {/* Action inbox */}
      <div>
        <h2 className="text-xl font-semibold mb-3">{t('dashboard.needsAttention')}</h2>
        {actionItems.length === 0 ? (
          <Card className="border-green-200 bg-green-50 dark:bg-green-950/20 dark:border-green-900">
            <CardContent className="flex items-center gap-3 py-6">
              <CheckCircle2 className="h-8 w-8 text-green-600" />
              <div>
                <p className="font-semibold">{t('dashboard.allCaughtUp')}</p>
                <p className="text-sm text-muted-foreground">
                  {t('dashboard.allCaughtUpBody')}
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {actionItems.map(item => (
              <Card key={item.key} className={item.urgent ? 'border-amber-300' : undefined}>
                <CardContent className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <item.icon className={`h-6 w-6 flex-shrink-0 ${item.urgent ? 'text-amber-600' : 'text-primary'}`} />
                    <p className="font-medium">{item.sentence}</p>
                  </div>
                  <Button onClick={() => navigate(item.to)} className="flex-shrink-0">
                    {item.buttonLabel}
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* COD cash + top sellers side by side. */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2">
        {/* COD cash. Revenue above is accrued at order date whether or not the
            money arrived; this tile is the other half — what is actually in
            hand. Cash sitting with a courier for weeks is the single easiest
            thing to lose track of in a COD business. */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">{t('dashboard.codCash')}</CardTitle>
            <Banknote className="h-5 w-5 text-primary" />
          </CardHeader>
          <CardContent className="space-y-1">
            <div
              className={`text-2xl font-bold ${
                Number(actions?.cod_pending_amount || 0) > 0 ? 'text-amber-600' : ''
              }`}
            >
              ₹{Number(actions?.cod_pending_amount || 0).toLocaleString('en-IN')}
            </div>
            <p className="text-xs text-muted-foreground">
              {t('dashboard.codUncollected', { count: actions?.cod_pending_count || 0 })}
            </p>
            {!!actions?.cod_pending_aged_count && (
              <p className="text-xs font-medium text-red-600">
                {t('dashboard.codAged', { count: actions.cod_pending_aged_count })}
              </p>
            )}
            <div className="flex justify-between text-sm border-t pt-1">
              <span className="text-muted-foreground">{t('dashboard.codConfirmedToday')}</span>
              <span className="font-semibold text-green-600">
                ₹{Number(actions?.cod_collected_today || 0).toLocaleString('en-IN')}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground pt-1">
              {t('dashboard.codNotePrefix')}
              <strong>{t('dashboard.codNoteStrong')}</strong>
              {t('dashboard.codNoteSuffix')}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">{t('dashboard.topSellers')}</CardTitle>
          </CardHeader>
          <CardContent>
            {topSellers.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('dashboard.topSellersEmpty')}</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="font-medium pb-1">{t('dashboard.topColProduct')}</th>
                    <th className="font-medium pb-1 text-right">{t('dashboard.topColUnits')}</th>
                    <th className="font-medium pb-1 text-right">{t('dashboard.topColRevenue')}</th>
                  </tr>
                </thead>
                <tbody>
                  {topSellers.map(item => (
                    <tr key={item.name} className="border-t">
                      <td className="py-1.5 pr-2">{item.name}</td>
                      <td className="py-1.5 text-right">{item.units}</td>
                      <td className="py-1.5 text-right">
                        ₹{Number(item.revenue ?? 0).toLocaleString('en-IN')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent orders */}
      <Card>
        <CardHeader>
          <CardTitle>{t('dashboard.recentOrders')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {stats?.recentOrders && stats.recentOrders.length > 0 ? (
              stats.recentOrders.map((order) => (
                <button
                  key={order.id}
                  onClick={() => navigate(`/orders?search=ORD-${String(order.id).padStart(6, '0')}`)}
                  className="flex w-full items-center justify-between border-b pb-3 text-left last:border-0"
                >
                  <div>
                    <p className="font-medium">{order.customerName}</p>
                    <p className="text-sm text-muted-foreground">
                      {new Date(order.createdAt).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="font-medium">₹{Number(order.totalAmount).toFixed(2)}</p>
                    <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
                      {t(`orderStatus.${order.status}`, { defaultValue: order.status })}
                    </span>{' '}
                    <span className="inline-flex items-center rounded-full bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
                      {order.paymentMethod} · {t(`paymentStatus.${order.paymentStatus}`, { defaultValue: order.paymentStatus })}
                    </span>
                  </div>
                </button>
              ))
            ) : (
              <p className="text-center text-muted-foreground">{t('dashboard.noRecentOrders')}</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* GST month line linking to the report. */}
      <p className="text-sm text-muted-foreground">
        {t('dashboard.gstMonthLine', {
          amount: Number(actions?.mtd_gst_net_collected || 0).toLocaleString('en-IN'),
        })}{' '}
        —{' '}
        <Button variant="link" className="px-0 text-sm" onClick={() => navigate('/gst')}>
          {t('dashboard.openGstReport')}
        </Button>
      </p>
    </div>
  );
};

export default Dashboard;
