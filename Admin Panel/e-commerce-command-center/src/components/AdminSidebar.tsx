import { NavLink } from '@/components/NavLink';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  BarChart3,
  Package,
  Layers,
  FolderOpen,
  LayoutList,
  Star,
  Table2,
  ShoppingCart,
  Receipt,
  Ticket,
  User,
  Users,
  MessagesSquare,
  Mail,
  Trash2,
  LogOut,
} from 'lucide-react';
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { useAuth } from '@/contexts/AuthContext';

// `titleKey` rather than a literal: the label is resolved at render time so a
// language switch re-labels the menu without remounting the sidebar.
const menuItems = [
  { titleKey: 'nav.dashboard', url: '/dashboard', icon: LayoutDashboard },
  { titleKey: 'nav.insights', url: '/insights', icon: BarChart3 },
  { titleKey: 'nav.products', url: '/products', icon: Package },
  { titleKey: 'nav.categories', url: '/categories', icon: FolderOpen },
  { titleKey: 'nav.sections', url: '/sections', icon: LayoutList },
  { titleKey: 'nav.combos', url: '/combos', icon: Layers },
  { titleKey: 'nav.reviews', url: '/reviews', icon: Star },
  { titleKey: 'nav.bulkEdit', url: '/bulk-edit', icon: Table2 },
  { titleKey: 'nav.orders', url: '/orders', icon: ShoppingCart },
  { titleKey: 'nav.gst', url: '/gst', icon: Receipt },
  { titleKey: 'nav.accounts', url: '/accounts', icon: Receipt },
  { titleKey: 'nav.customers', url: '/customers', icon: Users },
  { titleKey: 'nav.coupons', url: '/coupons', icon: Ticket },
  { titleKey: 'nav.recycleBin', url: '/recycle-bin', icon: Trash2 },
  { titleKey: 'nav.adminInfo', url: '/admin-info', icon: User },
  { titleKey: 'nav.contact', url: '/contact', icon: Mail },
  { titleKey: 'nav.conversations', url: '/conversations', icon: MessagesSquare },
];

export function AdminSidebar() {
  const { t } = useTranslation();
  const { state, isMobile, setOpenMobile } = useSidebar();
  const location = useLocation();
  const { logout, user } = useAuth();
  const currentPath = location.pathname;

  // Match sub-routes too: on /customers/5 the "Customers" item must still read
  // as the current section (exact equality left the whole menu unhighlighted).
  const isActive = (path: string) =>
    currentPath === path || currentPath.startsWith(`${path}/`);
  const isCollapsed = state === 'collapsed';

  // On phones the sidebar is a drawer over the page. Tapping a link used to
  // navigate *behind* it, leaving the admin looking at the menu they just used
  // and having to dismiss it by hand.
  const closeOnMobile = () => { if (isMobile) setOpenMobile(false); };

  // Get display name from user profile
  const displayName = user 
    ? (user.first_name && user.last_name 
        ? `${user.first_name} ${user.last_name}` 
        : user.username || user.email)
    : t('nav.admin');

  return (
    <Sidebar className="transition-all duration-300">
      <SidebarContent>
        <div className="p-4 border-b">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
              <User className="h-5 w-5 text-primary" />
            </div>
            {!isCollapsed && (
              <div className="min-w-0">
                <p className="font-semibold text-sm truncate">{displayName}</p>
                <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
              </div>
            )}
          </div>
        </div>

        <SidebarGroup>
          <SidebarGroupLabel className={cn(isCollapsed && 'sr-only')}>
            {t('nav.mainMenu')}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => (
                <SidebarMenuItem key={item.url}>
                  <SidebarMenuButton asChild>
                    <NavLink
                      to={item.url}
                      onClick={closeOnMobile}
                      className={cn(
                        'flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-sidebar-accent',
                        isActive(item.url) && 'bg-sidebar-accent text-sidebar-primary'
                      )}
                    >
                      <item.icon className="h-5 w-5 flex-shrink-0" />
                      {!isCollapsed && <span>{t(item.titleKey)}</span>}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              
              <SidebarMenuItem>
                <SidebarMenuButton asChild>
                  <button
                    onClick={logout}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-destructive transition-colors hover:bg-sidebar-accent"
                  >
                    <LogOut className="h-5 w-5 flex-shrink-0" />
                    {!isCollapsed && <span>{t('nav.logout')}</span>}
                  </button>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
