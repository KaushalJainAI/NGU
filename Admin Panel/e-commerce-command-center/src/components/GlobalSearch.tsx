import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { globalSearch, GlobalSearchResults } from '@/api/adminSearch';
import { Input } from '@/components/ui/input';
import { Search, ShoppingCart, Package, User, Ticket, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/** One search box for the whole panel: type an order number, customer name or
 *  phone, product, or coupon code — click a result to jump to it. */
export const GlobalSearch = () => {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GlobalSearchResults | null>(null);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // Debounced fetch: wait for the admin to stop typing.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults(null);
      setOpen(false);
      return;
    }
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await globalSearch(q);
        setResults(res.data);
        setActiveIndex(0);
        setOpen(true);
      } catch {
        setResults(null);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Close when clicking anywhere else.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  // Ctrl/⌘+K focuses the box from anywhere in the panel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const go = (path: string) => {
    setOpen(false);
    setQuery('');
    navigate(path);
  };

  // Flat, in-render-order list of every result so the arrow keys and Enter can
  // walk it. Without this the dropdown was mouse-only: pressing Enter in the
  // box did nothing at all.
  const flatResults: { key: string; path: string }[] = results
    ? [
        ...results.orders.map(o => ({ key: `o-${o.id}`, path: `/orders?search=${o.id}` })),
        ...results.products.map(p => ({
          key: `p-${p.id}`, path: `/products?search=${encodeURIComponent(p.name)}`,
        })),
        ...results.customers.map(c => ({ key: `c-${c.id}`, path: `/customers/${c.id}` })),
        ...results.coupons.map(c => ({ key: `cp-${c.id}`, path: '/coupons' })),
      ]
    : [];

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (!open || flatResults.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex(i => (i + 1) % flatResults.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex(i => (i - 1 + flatResults.length) % flatResults.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      go(flatResults[Math.min(activeIndex, flatResults.length - 1)].path);
    }
  };

  const isEmpty =
    results &&
    !results.orders.length && !results.products.length &&
    !results.customers.length && !results.coupons.length;

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="py-1">
      <p className="px-3 py-1 text-xs font-semibold text-muted-foreground uppercase">{title}</p>
      {children}
    </div>
  );

  const Row = ({ icon: Icon, main, sub, onClick, rowKey }: {
    icon: typeof Search; main: string; sub?: string; onClick: () => void; rowKey: string;
  }) => (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => {
        const i = flatResults.findIndex(r => r.key === rowKey);
        if (i >= 0) setActiveIndex(i);
      }}
      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent ${
        flatResults[activeIndex]?.key === rowKey ? 'bg-accent' : ''
      }`}
    >
      <Icon className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
      <span className="truncate font-medium">{main}</span>
      {sub && <span className="ml-auto flex-shrink-0 text-xs text-muted-foreground">{sub}</span>}
    </button>
  );

  return (
    <div ref={containerRef} className="relative flex-1 max-w-md">
      <div className="relative">
        {searching
          ? <Loader2 className="absolute left-2.5 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />
          : <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />}
        <Input
          ref={inputRef}
          placeholder={t('search.placeholder')}
          className="pl-8 h-9"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onInputKeyDown}
          onFocus={() => { if (results) setOpen(true); }}
        />
      </div>

      {open && results && (
        <div className="absolute left-0 right-0 top-11 z-50 max-h-[70vh] overflow-y-auto rounded-md border bg-popover shadow-lg">
          {isEmpty && (
            <p className="px-3 py-4 text-sm text-muted-foreground text-center">
              {t('search.empty', { query: query.trim() })}
            </p>
          )}
          {results.orders.length > 0 && (
            <Section title={t('search.orders')}>
              {results.orders.map(o => (
                <Row
                  key={`o-${o.id}`}
                  rowKey={`o-${o.id}`}
                  icon={ShoppingCart}
                  main={`${o.order_number} — ${o.customer}`}
                  sub={`₹${o.total} · ${o.status}`}
                  onClick={() => go(`/orders?search=${o.id}`)}
                />
              ))}
            </Section>
          )}
          {results.products.length > 0 && (
            <Section title={t('search.products')}>
              {results.products.map(p => (
                <Row
                  key={`p-${p.id}`}
                  rowKey={`p-${p.id}`}
                  icon={Package}
                  main={p.name}
                  sub={`₹${p.price} · ${t('search.inStock', { count: p.stock })}`}
                  onClick={() => go(`/products?search=${encodeURIComponent(p.name)}`)}
                />
              ))}
            </Section>
          )}
          {results.customers.length > 0 && (
            <Section title={t('search.customers')}>
              {results.customers.map(c => (
                <Row
                  key={`c-${c.id}`}
                  rowKey={`c-${c.id}`}
                  icon={User}
                  main={c.name}
                  sub={c.phone || c.email}
                  onClick={() => go(`/customers/${c.id}`)}
                />
              ))}
            </Section>
          )}
          {results.coupons.length > 0 && (
            <Section title={t('search.coupons')}>
              {results.coupons.map(c => (
                <Row
                  key={`cp-${c.id}`}
                  rowKey={`cp-${c.id}`}
                  icon={Ticket}
                  main={c.code}
                  sub={c.is_active ? t('common.active') : t('common.inactive')}
                  onClick={() => go('/coupons')}
                />
              ))}
            </Section>
          )}
        </div>
      )}
    </div>
  );
};
