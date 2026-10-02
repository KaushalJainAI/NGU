import { useTranslation } from 'react-i18next';
import { Languages, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { SUPPORTED_LANGUAGES, LANG_STORAGE_KEY, type LanguageCode } from '@/i18n';

/**
 * Panel language picker.
 *
 * Unlike the storefront's switcher this does NOT reload the page: the admin API
 * returns raw catalogue data (the source-of-truth product names an admin edits),
 * never server-translated copy, so swapping the UI strings in place is enough —
 * and a reload here would throw away unsaved dialog state.
 */
export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { t, i18n } = useTranslation();

  const current = (i18n.resolvedLanguage || i18n.language || 'en').split('-')[0];
  const currentLabel =
    SUPPORTED_LANGUAGES.find((l) => l.code === current)?.label ?? 'English';

  const choose = (code: LanguageCode) => {
    if (code === current) return;
    try {
      localStorage.setItem(LANG_STORAGE_KEY, code);
    } catch {
      /* private mode — the choice just won't survive a refresh */
    }
    i18n.changeLanguage(code);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {compact ? (
          <Button variant="ghost" size="icon" aria-label={t('common.language')}>
            <Languages className="h-5 w-5" />
          </Button>
        ) : (
          <Button variant="ghost" size="sm" className="gap-2" aria-label={t('common.language')}>
            <Languages className="h-4 w-4" />
            <span className="hidden sm:inline">{currentLabel}</span>
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[10rem] bg-popover">
        {SUPPORTED_LANGUAGES.map((l) => (
          <DropdownMenuItem
            key={l.code}
            onClick={() => choose(l.code)}
            className="flex items-center justify-between gap-3 cursor-pointer"
          >
            <span>{l.label}</span>
            {l.code === current && <Check className="h-4 w-4 text-primary" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
