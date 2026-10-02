import { useEffect, useRef, useState } from 'react';
import { getCustomers, Customer } from '@/api/customers';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Loader2, User, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface CustomerPickerProps {
  /** Bound customer id, or null for "no one in particular". */
  value: number | null;
  /** Email of the bound customer when already known (editing an existing
   *  record), so the picker can name them without a refetch. */
  valueLabel?: string | null;
  onChange: (id: number | null, email: string | null) => void;
  /** Shown in the empty search box. Defaults to a translated prompt. */
  placeholder?: string;
  id?: string;
}

/**
 * Search-as-you-type customer selector, in the same shape as GlobalSearch:
 * a plain input, a 300ms debounce, and an absolutely-positioned result list.
 * Once a customer is chosen it collapses to a chip with a clear button, so the
 * bound identity is always visible rather than hidden behind a dropdown.
 */
export const CustomerPicker = ({
  value,
  valueLabel,
  onChange,
  placeholder,
  id,
}: CustomerPickerProps) => {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Customer[] | null>(null);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

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
        const res = await getCustomers(q);
        setResults(res.data.results || []);
        setOpen(true);
      } catch {
        setResults(null);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Close the dropdown when clicking anywhere else.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const select = (customer: Customer) => {
    onChange(customer.id, customer.email);
    setQuery('');
    setResults(null);
    setOpen(false);
  };

  if (value !== null) {
    return (
      <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
        <User className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate text-sm">
          {valueLabel || t('customerPicker.customerNumber', { id: value })}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          onClick={() => onChange(null, null)}
          title={t('customerPicker.remove')}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        id={id}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => { if (results) setOpen(true); }}
        placeholder={placeholder ?? t('customerPicker.placeholder')}
        autoComplete="off"
      />
      {searching && (
        <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
      )}
      {open && results && (
        <div className="absolute z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-md border bg-popover shadow-lg">
          {results.length === 0 ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">{t('customerPicker.noMatch')}</p>
          ) : (
            results.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => select(c)}
                className="flex w-full flex-col items-start px-3 py-2 text-left hover:bg-accent"
              >
                <span className="text-sm font-medium">{c.email}</span>
                <span className="text-xs text-muted-foreground">
                  {[c.name, c.phone].filter(Boolean).join(' · ') || t('customerPicker.noName')}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
};
