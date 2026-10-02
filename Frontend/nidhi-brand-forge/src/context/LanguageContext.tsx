import React, { createContext, useContext, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  SUPPORTED_LANGUAGES,
  LANGUAGE_CODES,
  LANG_STORAGE_KEY,
  type LanguageCode,
} from '@/i18n/index';

interface LanguageContextType {
  language: LanguageCode;
  setLanguage: (lang: LanguageCode) => void;
  toggleLanguage: () => void;
  languages: typeof SUPPORTED_LANGUAGES;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

const normalize = (lng?: string): LanguageCode => {
  if (!lng) return 'en';
  if ((LANGUAGE_CODES as string[]).includes(lng)) return lng as LanguageCode;
  const base = lng.split('-')[0];
  if ((LANGUAGE_CODES as string[]).includes(base)) return base as LanguageCode;
  return 'en';
};

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { i18n } = useTranslation();
  const [language, setLanguageState] = useState<LanguageCode>(
    normalize(i18n.resolvedLanguage || i18n.language)
  );

  // Keep local state in sync if the language changes from anywhere.
  useEffect(() => {
    const handler = (lng: string) => setLanguageState(normalize(lng));
    i18n.on('languageChanged', handler);
    return () => {
      i18n.off('languageChanged', handler);
    };
  }, [i18n]);

  const setLanguage = (lang: LanguageCode) => {
    // No-op if unchanged, so we don't reload the page for nothing.
    if (lang === language) return;

    // Persist the choice BEFORE reloading so i18n (lookupLocalStorage) and the
    // API X-Language header both pick it up on the next page load.
    try {
      localStorage.setItem(LANG_STORAGE_KEY, lang);
    } catch {
      /* ignore storage failures (private mode) */
    }
    i18n.changeLanguage(lang);
    setLanguageState(lang);

    // Full refresh: server-translated content (products, categories, etc.) is
    // fetched with the X-Language header, so a reload re-fetches everything in
    // the newly selected language rather than only swapping static UI strings.
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  // Kept for backward compatibility; flips between English and Hindi.
  const toggleLanguage = () => setLanguage(language === 'en' ? 'hi' : 'en');

  return (
    <LanguageContext.Provider
      value={{ language, setLanguage, toggleLanguage, languages: SUPPORTED_LANGUAGES }}
    >
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (context === undefined) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};
