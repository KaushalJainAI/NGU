import api from './axiosInstance';

export interface RecentOrder {
  id: number;
  customerName: string;
  totalAmount: number;
  status: string;
  createdAt: string;
  paymentMethod: string;
  paymentStatus: string;
}

export interface TopProduct {
  name: string;
  units: number;
  revenue: string;
}

export interface DashboardStats {
  totalProducts: number;
  totalCombos: number;
  totalOrders: number;
  activeCoupons: number;
  recentOrders: RecentOrder[];
}

// Fetch dashboard statistics
export const getDashboardStats = () =>
  api.get<DashboardStats>('/dashboard/');

export interface LowStockItem {
  /** The PRODUCT's id (links to the product). */
  id: number;
  /** The size that is running low — a product can have several. */
  variant_id?: number;
  name: string;
  /** The size's label, e.g. "500g". */
  size?: string;
  stock: number;
}

// "Today" action inbox: everything that currently needs the admin's attention.
export interface DashboardActions {
  orders_to_confirm: number;
  orders_to_ship: number;
  low_stock_count: number;
  low_stock_items: LowStockItem[];
  chats_waiting: number;
  /** Active chats whose last message is the customer's — nobody has replied. */
  unread_chats: number;
  /** Contact-form messages still in the "new" (unread) state. */
  new_contacts: number;
  stuck_payments: number;
  today_orders: number;
  /** GROSS sales collected today — reconciles against gateway settlements. */
  today_revenue: string;
  /** What was sold, net of the tax collected on it (revenue − output tax). */
  today_taxable_sales: string;
  mtd_taxable_sales: string;
  /**
   * GST collected FROM CUSTOMERS on sales (output tax) — a record of money
   * taken. It is NOT the amount to remit: that is this minus input tax credit
   * on purchases, which this system does not track and does not guess. Never
   * label any of these "payable".
   */
  today_gst_collected: string;
  /** Month-to-date GST collected — GST is filed monthly, so this is the useful one. */
  mtd_gst_collected: string;
  /** GST reversed by refunds, counted on the day the refund happened. */
  today_gst_refunded: string;
  mtd_gst_refunded: string;
  /** Collected − refunded: the net tax actually held for the period. */
  today_gst_net_collected: string;
  mtd_gst_net_collected: string;
  today_refunds: string;
  mtd_refunds: string;
  /** Delivery fees charged to customers today. */
  today_shipping_collected: string;
  /** What couriers charged us today, summed over orders where it was recorded. */
  today_shipping_cost: string;
  today_shipping_margin: string;
  /** Average courier cost across only those orders with a cost recorded. */
  today_avg_shipping_cost: string;
  /** How many of today's orders have a courier cost recorded (denominator above). */
  today_shipping_cost_recorded: number;
  /**
   * COD cash ledger — deliberately separate from revenue/GST above, which
   * accrue at order date. This is purely "has the money arrived yet".
   *
   * `cod_pending_*` is a point-in-time figure: dispatched or delivered COD
   * orders nobody has ticked "Paid in cash" on — i.e. cash the couriers are
   * still holding. `aged` is the slice older than a week, the part worth chasing.
   */
  cod_pending_amount: string;
  cod_pending_count: number;
  cod_pending_aged_count: number;
  /** COD cash confirmed today, bucketed by CONFIRMATION date, not order date. */
  cod_collected_today: string;
  /**
   * Revenue net of refunds. `today_revenue` stays GROSS because that is what
   * reconciles against gateway settlements — but gross beside a separate
   * refunds figure reads as net to almost everyone, so both are given.
   */
  today_net_revenue: string;
  mtd_revenue: string;
  mtd_net_revenue: string;
  /** Razorpay's total fee this month — a real expense that was previously invisible. */
  mtd_gateway_fee: string;
  /**
   * GST inside that fee — input tax credit we happen to have evidence for.
   * Shown on its own, never netted off the collected figure: it is one input
   * among many this system can't see, and subtracting it would make the
   * result look filed-ready when it isn't.
   */
  mtd_gateway_tax: string;
  /** WP5 rebuild — real (paid/booked) sales. Money is a string, counts are numbers. */
  today_sales: string;
  today_real_orders: number;
  today_aov: string;
  today_online_received: string;
  today_cod_booked: string;
  last_week_same_day_sales: string;
  today_sales_delta_pct: number | null;
  mtd_sales: string;
  prev_mtd_sales: string;
  mtd_sales_delta_pct: number | null;
  orders_unshipped_aged: number;
  out_of_stock_count: number;
  invoices_missing: number;
  failed_payments_today: number;
  unclassified_hsn_count: number;
  top_products_7d: TopProduct[];
}

export const getDashboardActions = () =>
  api.get<DashboardActions>('/dashboard/actions/');

// Trigger the daily/weekly store-owner email on demand (preview / delivery test).
export const sendReport = (type: 'daily' | 'weekly') =>
  api.post<{ sent: boolean; type: string }>('/dashboard/send-report/', { type });
