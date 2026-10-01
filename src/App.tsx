import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readEnv } from "@/config/runtimeEnv";
import { BrowserRouter, Routes, Route, useLocation, Navigate } from "react-router-dom";
import Index from "./pages/Index";
import Products from "./pages/Products";
import Combos from "./pages/Combos";
import ProductDetail from "./pages/ProductDetail";
import ComboDetail from "./pages/ComboDetail";
import About from "./pages/About";
import Contact from "./pages/Contact";
import NotFound from "./pages/NotFound";
import SearchResults from "./pages/SearchResults";
import MyOrders from "./pages/MyOrders";
import ShippingPolicy from "./pages/ShippingPolicy";
import ReturnPolicy from "./pages/ReturnPolicy";
import PrivacyPolicy from "./pages/PrivacyPolicy";
import TermsAndConditions from "./pages/TermsAndConditions";
import FAQ from "./pages/FAQ";
import OrderSuccess from "./pages/OrderSuccess";
import OfferZone from "./pages/OfferZone";
import Profile from "./pages/Profile";
import Cart from "./pages/Cart";
import Billing from "./pages/Billing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Favorites from "./pages/Favorites";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import InterestSuccess from "./pages/InterestSuccess";
import { CartProvider } from "./context/CartContext";
import { AuthProvider } from "./context/AuthContext";
import { LanguageProvider } from "./context/LanguageContext";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { FavoritesProvider } from "./context/FavoritesContext";
import ScrollToTop from "./functions/ScrollToTop";
import { usePageTracking } from "./hooks/usePageTracking";
import Navbar from "./components/Navbar";
import UspRibbon from "./components/UspRibbon";
import MobileFooter from "./components/MobileFooter";
import FloatingCartBar from "./components/FloatingCartBar";
import AssistantWidget from "./components/AssistantWidget";
import FloatingWhatsApp from "./components/FloatingWhatsApp";
import CookieConsent from "./components/CookieConsent";
import ErrorBoundary from "./components/ErrorBoundary";

const queryClient = new QueryClient();

// Routes wrapper (AP12: the per-route entrance animation is gone — every
// navigation replayed it, which reads as jank, not polish).
const AnimatedRoutes = () => {
  const location = useLocation();
  usePageTracking();

  return (
    <div>
      {/* Keyed on the path so navigating away from a crashed page clears the
           error and renders the next route normally. */}
      <ErrorBoundary key={location.pathname}>
      <Routes location={location}>
        <Route path="/" element={<Index />} />
        <Route path="/products" element={<Products />} />
        <Route path="/combos" element={<Combos />} />
        <Route path="/products/:id" element={<ProductDetail />} />
        <Route path="/combos/:id" element={<ComboDetail />} />
        <Route path="/about" element={<About />} />
        <Route path="/contact" element={<Contact />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/cart" element={<Cart />} />
        <Route path="/billing" element={<Billing />} />
        {/* Common alias — external/bookmarked /checkout links resolve to billing */}
        <Route path="/checkout" element={<Navigate to="/billing" replace />} />
        <Route path="/favorites" element={<Favorites />} />
        {/* Common alias — external/bookmarked /wishlist links resolve to favorites */}
        <Route path="/wishlist" element={<Navigate to="/favorites" replace />} />
        <Route path="/search" element={<SearchResults />} />
        <Route path="/my-orders" element={<MyOrders />} />
        <Route path="/shipping-policy" element={<ShippingPolicy />} />
        <Route path="/return-policy" element={<ReturnPolicy />} />
        <Route path="/privacy-policy" element={<PrivacyPolicy />} />
        <Route path="/terms" element={<TermsAndConditions />} />
        <Route path="/faq" element={<FAQ />} />
        <Route path="/order-success" element={<OrderSuccess />} />
        <Route path="/interest-success" element={<InterestSuccess />} />
        <Route path="/offer-zone" element={<OfferZone />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      </ErrorBoundary>
    </div>
  );
};

const App = () => (
  // Outermost boundary: the route-level one above cannot catch a crash in the
  // providers themselves (auth, cart, i18n), which is exactly the class of
  // failure that would otherwise render a blank white page.
  <ErrorBoundary>
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <GoogleOAuthProvider clientId={readEnv("VITE_GOOGLE_CLIENT_ID") || ""}>
        <AuthProvider>
          <LanguageProvider>
            <FavoritesProvider>
              <CartProvider>
                <Toaster />
                <Sonner />
                <BrowserRouter>
                  <ScrollToTop />
                  {/* USP ribbon + Navbar are outside AnimatedRoutes so they don't reload on page change */}
                  <UspRibbon />
                  <Navbar />
                  <AnimatedRoutes />
                  {/* MobileFooter is outside AnimatedRoutes so it doesn't reload on page change */}
                  <MobileFooter />
                  <FloatingCartBar />
                  <FloatingWhatsApp />
                  {/* Non-essential chrome: a widget crash must not replace the
                      storefront with a full-page error. */}
                  <ErrorBoundary fallback={null}><AssistantWidget /></ErrorBoundary>
                  <CookieConsent />
                </BrowserRouter>
              </CartProvider>
            </FavoritesProvider>
          </LanguageProvider>
        </AuthProvider>
      </GoogleOAuthProvider>
    </TooltipProvider>
  </QueryClientProvider>
  </ErrorBoundary>
);

export default App;
