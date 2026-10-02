import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import enCommon from './locales/en/common.json';
import enNav from './locales/en/nav.json';
import enDashboard from './locales/en/dashboard.json';
import enInsights from './locales/en/insights.json';
import enCatalog from './locales/en/catalog.json';
import enProducts from './locales/en/products.json';
import enCombos from './locales/en/combos.json';
import enOrders from './locales/en/orders.json';
import enReviews from './locales/en/reviews.json';
import enAdmin from './locales/en/admin.json';
import enAccounts from './locales/en/accounts.json';

import hiCommon from './locales/hi/common.json';
import hiNav from './locales/hi/nav.json';
import hiDashboard from './locales/hi/dashboard.json';
import hiInsights from './locales/hi/insights.json';
import hiCatalog from './locales/hi/catalog.json';
import hiProducts from './locales/hi/products.json';
import hiCombos from './locales/hi/combos.json';
import hiOrders from './locales/hi/orders.json';
import hiReviews from './locales/hi/reviews.json';
import hiAdmin from './locales/hi/admin.json';
import hiAccounts from './locales/hi/accounts.json';

/**
 * Languages the ADMIN PANEL offers. Deliberately shorter than the storefront's
 * six (src/i18n/index.ts in nidhi-brand-forge): the panel is used by the shop
 * owner and staff, not customers, so English + Hindi is the whole audience.
 */
export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

export const LANGUAGE_CODES = SUPPORTED_LANGUAGES.map((l) => l.code) as LanguageCode[];

/**
 * ⚠ NOT the storefront's `site_lang`. The panel is served from /panel/ on the
 * SAME ORIGIN as the storefront, so the two share one localStorage. Reusing the
 * key would make an admin switching the panel to Hindi silently flip the
 * customer-facing site for themselves too (and vice versa).
 */
export const LANG_STORAGE_KEY = 'admin_lang';

// The locale files are split per area purely so they stay reviewable; i18next
// sees one flat `translation` namespace with top-level sections.
const en = {
  ...enCommon,
  ...enNav,
  ...enDashboard,
  ...enInsights,
  ...enCatalog,
  ...enProducts,
  ...enCombos,
  ...enOrders,
  ...enReviews,
  ...enAdmin,
  ...enAccounts,
};

const hi = {
  ...hiCommon,
  ...hiNav,
  ...hiDashboard,
  ...hiInsights,
  ...hiCatalog,
  ...hiProducts,
  ...hiCombos,
  ...hiOrders,
  ...hiReviews,
  ...hiAdmin,
  ...hiAccounts,
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      hi: { translation: hi },
    },
    fallbackLng: 'en',
    supportedLngs: LANGUAGE_CODES,
    nonExplicitSupportedLngs: true,
    detection: {
      // No `navigator` here, unlike the storefront: a Hindi-locale browser
      // should not silently switch an admin's console. Default is English
      // until it is chosen explicitly.
      order: ['localStorage'],
      lookupLocalStorage: LANG_STORAGE_KEY,
      caches: ['localStorage'],
    },
    interpolation: { escapeValue: false },
    // An empty string in a locale file falls back to English rather than
    // rendering blank chrome.
    returnEmptyString: false,
  });

export default i18n;
